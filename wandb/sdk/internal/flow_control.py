"""Flow Control.

States:
    FORWARDING
    PAUSING

New messages:
    pb.SenderMarkRequest    writer -> sender (empty message)
    pb.StatusReportRequest  sender -> writer (reports current sender progress)
    pb.SenderReadRequest    writer -> sender (requests read of transaction log)

Thresholds:
    Threshold_High_MaxOutstandingData       - When above this, stop sending requests to sender
    Threshold_Mid_StartSendingReadRequests - When below this, start sending read requests
    Threshold_Low_RestartSendingData       - When below this, start sending normal records

State machine:
    FORWARDING
      -> PAUSED if should_pause
    PAUSING
      -> FORWARDING if should_unpause
      -> PAUSING if should_recover
      -> PAUSING if should_quiesce

"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

from wandb.proto import wandb_internal_pb2 as pb

# from wandb.proto import wandb_telemetry_pb2 as tpb
# from wandb.sdk.lib import fsm, telemetry
from wandb.sdk.lib import fsm

from .settings_static import SettingsStatic

if TYPE_CHECKING:
    from wandb.proto.wandb_internal_pb2 import Record

logger = logging.getLogger(__name__)


def _get_request_type(record: "Record") -> Optional[str]:
    record_type = record.WhichOneof("record_type")
    if record_type != "request":
        return None
    request_type = record.request.WhichOneof("request_type")
    return request_type


def _is_local_record(record: "Record") -> bool:
    return record.control.local


def _is_control_record(record: "Record") -> bool:
    return record.control.flow_control


@dataclass
class StateContext:
    last_forwarded_offset: int = 0
    last_sent_offset: int = 0
    last_written_offset: int = 0


class FlowControl:
    # _telemetry_obj: tpb.TelemetryRecord
    # _telemetry_overflow: bool
    _fsm: fsm.FsmWithContext["Record", StateContext]

    def __init__(
        self,
        settings: SettingsStatic,
        forward_record: Callable[["Record"], None],
        write_record: Callable[["Record"], int],
        send_mark: Callable[[], None],
        recover_records: Callable[[int, int], None],
        _threshold_bytes_high: int = 4 * 1024 * 1024,  # 4MiB
        _threshold_bytes_mid: int = 2 * 1024 * 1024,  # 2MiB
        _threshold_bytes_low: int = 1 * 1024 * 1024,  # 1MiB
    ) -> None:

        # thresholds to define when to PAUSE, RESTART, FORWARDING
        if settings._ram_buffer:
            _threshold_bytes_high = settings._ram_buffer
            _threshold_bytes_mid = settings._ram_buffer // 2
            _threshold_bytes_low = settings._ram_buffer // 4

        # self._telemetry_obj = tpb.TelemetryRecord()
        # self._telemetry_overflow = False

        # FSM definition
        state_forwarding = StateForwarding(
            forward_record=forward_record,
            send_mark=send_mark,
            threshold_pause=_threshold_bytes_high,
        )
        state_pausing = StatePausing(
            forward_record=forward_record,
            recover_records=recover_records,
            threshold_recover=_threshold_bytes_mid,
            threshold_forward=_threshold_bytes_low,
        )
        self._fsm = fsm.FsmWithContext(
            states=[state_forwarding, state_pausing],
            table={
                StateForwarding: [
                    fsm.FsmEntry(
                        state_forwarding._should_pause,
                        StatePausing,
                        state_forwarding._pause,
                    ),
                ],
                StatePausing: [
                    fsm.FsmEntry(
                        state_pausing._should_unpause,
                        StateForwarding,
                        state_pausing._unpause,
                    ),
                    fsm.FsmEntry(
                        state_pausing._should_recover,
                        StatePausing,
                        state_pausing._recover,
                    ),
                    fsm.FsmEntry(
                        state_pausing._should_quiesce,
                        StatePausing,
                        state_pausing._quiesce,
                    ),
                ],
            },
        )

    # def _telemetry_record_overflow(self) -> None:
    #     if self._telemetry_overflow:
    #         return
    #     self._telemetry_overflow = True
    #     with telemetry.context(obj=self._telemetry_obj) as tel:
    #         tel.feature.flow_control_overflow = True
    #     record = pb.Record()
    #     record.telemetry.CopyFrom(self._telemetry_obj)
    #     self._forward_record(record)

    def flush(self) -> None:
        # TODO(mempressure): what do we do here, how do we make sure we dont have work in pause state
        pass

    def flow(self, record: "Record") -> None:
        self._fsm.input(record)


class StateShared:
    _context: StateContext

    def __init__(self) -> None:
        self._context = StateContext()

    def _update_written_offset(self, record: "Record") -> None:
        end_offset = record.control.end_offset
        if end_offset:
            self._context.last_written_offset = end_offset

    def _update_forwarded_offset(self) -> None:
        self._context.last_forwarded_offset = self._context.last_written_offset

    def _process(self, record: "Record") -> None:
        request_type = _get_request_type(record)
        if not request_type:
            return
        process_str = f"_process_{request_type}"
        process_handler: Optional[Callable[["pb.Record"], None]] = getattr(
            self, process_str, None
        )
        if not process_handler:
            return
        process_handler(record)

    def _process_status_report(self, record: "Record") -> None:
        sent_offset = record.request.status_report.sent_offset
        self._context.last_sent_offset = sent_offset

    def on_exit(self, record: "Record") -> StateContext:
        return self._context

    def on_enter(self, record: "Record", context: StateContext) -> None:
        self._context = context

    @property
    def _behind_bytes(self) -> int:
        return self._context.last_forwarded_offset - self._context.last_sent_offset


class StateForwarding(StateShared):
    _forward_record: Callable[["Record"], None]
    _send_mark: Callable[[], None]
    _threshold_pause: int

    def __init__(
        self,
        forward_record: Callable[["Record"], None],
        send_mark: Callable[[], None],
        threshold_pause: int,
    ) -> None:
        super().__init__()
        self._forward_record = forward_record
        self._send_mark = send_mark
        self._threshold_pause = threshold_pause

    def _should_pause(self, record: "Record") -> bool:
        return self._behind_bytes >= self._threshold_pause

    def _pause(self, record: "Record") -> None:
        self._send_mark()

    def on_check(self, record: "Record") -> None:
        self._update_written_offset(record)
        self._process(record)
        if not _is_control_record(record):
            self._forward_record(record)
        self._update_forwarded_offset()


class StatePausing(StateShared):
    _forward_record: Callable[["Record"], None]
    _recover_records: Callable[[int, int], None]
    _threshold_recover: int
    _threshold_forward: int

    def __init__(
        self,
        forward_record: Callable[["Record"], None],
        recover_records: Callable[[int, int], None],
        threshold_recover: int,
        threshold_forward: int,
    ) -> None:
        super().__init__()
        self._forward_record = forward_record
        self._recover_records = recover_records
        self._threshold_recover = threshold_recover
        self._threshold_forward = threshold_forward

    def _should_unpause(self, record: "Record") -> bool:
        return self._behind_bytes < self._threshold_forward

    def _unpause(self, record: "Record") -> None:
        self._quiesce(record)

    def _should_recover(self, record: "Record") -> bool:
        return self._behind_bytes < self._threshold_recover

    def _recover(self, record: "Record") -> None:
        self._quiesce(record)

    def _should_quiesce(self, record: "Record") -> bool:
        return _is_local_record(record) and not _is_control_record(record)

    def _quiesce(self, record: "Record") -> None:
        start = self._context.last_forwarded_offset
        end = self._context.last_written_offset
        if start != end:
            self._recover_records(start, end)
        if _is_local_record(record) and not _is_control_record(record):
            self._forward_record(record)
        self._update_forwarded_offset()

    def on_check(self, record: "Record") -> None:
        self._update_written_offset(record)
        self._process(record)
