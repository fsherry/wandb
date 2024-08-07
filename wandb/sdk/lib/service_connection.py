import atexit
import os
import threading
from typing import Optional

from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_server_pb2 as spb
from wandb.proto import wandb_settings_pb2
from wandb.sdk.interface.interface import InterfaceBase
from wandb.sdk.interface.interface_sock import InterfaceSock
from wandb.sdk.lib import service_token
from wandb.sdk.lib.mailbox import Mailbox
from wandb.sdk.lib.sock_client import SockClient
from wandb.sdk.service import service


class WandbServiceNotOwnedError(Exception):
    """Raised when the current process does not own the service process."""


def connect_to_service(settings: "pb.Settings") -> "ServiceConnection":
    """Connects to the service process, starting one up if necessary."""
    conn = _try_connect_to_existing_service()
    if conn:
        return conn

    return _start_and_connect_service(settings)


def _try_connect_to_existing_service() -> "Optional[ServiceConnection]":
    """Attemps to connect to an existing service process."""
    token = service_token.get_service_token()
    if not token:
        return None

    # Only localhost sockets are supported below.
    assert token.host == "localhost"
    client = SockClient()

    # TODO: This may block indefinitely if the service is unhealthy.
    client.connect(token.port)

    return ServiceConnection(client=client, proc=None)


def _start_and_connect_service(settings: "pb.Settings") -> "ServiceConnection":
    """Starts a service process and returns a connection to it.

    An atexit hook is registered to tear down the service process and wait for
    it to complete. The hook does not run in processes started using the
    multiprocessing module.
    """
    proc = service._Service(settings)
    proc.start()

    port = proc.sock_port
    assert port
    client = SockClient()
    client.connect(port)

    service_token.put_service_token(
        parent_pid=str(os.getpid()),
        transport="tcp",
        host="localhost",
        port=port,
    )

    conn = ServiceConnection(client=client, proc=proc)

    atexit.register(conn._teardown_atexit)

    return conn


class ServiceConnection:
    """A connection to the W&B internal service process."""

    def __init__(self, client: "SockClient", proc: "Optional[service._Service]"):
        self._lock = threading.Lock()
        self._torn_down = False

        self._client = client
        self._proc = proc

    def make_interface(self, mailbox: "Mailbox") -> "InterfaceBase":
        """Returns an interface for communicating with the service."""
        return InterfaceSock(self._client, mailbox)

    def send_record(self, record: "pb.Record") -> None:
        """Sends data to the service."""
        self._client.send_record_publish(record)

    def inform_init(
        self,
        settings: "wandb_settings_pb2.Settings",
        run_id: str,
    ) -> None:
        """Sends an init request to the service."""
        request = spb.ServerInformInitRequest()
        request.settings.CopyFrom(settings)
        request._info.stream_id = run_id
        self._client.send(inform_init=request)

    def inform_finish(self, run_id: str) -> None:
        """Sends an finish request to the service."""
        request = spb.ServerInformFinishRequest()
        request._info.stream_id = run_id
        self._client.send(inform_finish=request)

    def inform_attach(
        self,
        attach_id: str,
    ) -> "wandb_settings_pb2.Settings":
        """Sends an attach request to the service."""
        request = spb.ServerInformAttachRequest()
        request._info.stream_id = attach_id
        response = self._client.send_and_recv(inform_attach=request)
        return response.inform_attach_response.settings

    def inform_start(
        self,
        settings: "wandb_settings_pb2.Settings",
        run_id: str,
    ) -> None:
        """Sends a start request to the service."""
        request = spb.ServerInformStartRequest()
        request.settings.CopyFrom(settings)
        request._info.stream_id = run_id
        self._client.send(inform_start=request)

    def _teardown_atexit(self):
        """Shuts down the service process with a 0 exit code."""
        self.teardown(0)

    def teardown(self, exit_code: int) -> int:
        """Shut downs down the service process and returns its exit code.

        Calls after the initial one are no-ops.

        Returns:
            The exit code of the service process.

        Raises:
            WandbServiceNotOwnedError: If the current process did not start
                the service process.
        """
        if not self._proc:
            raise WandbServiceNotOwnedError(
                "Cannot tear down service started by different process",
            )

        with self._lock:
            if self._torn_down:
                return
            self._torn_down = True

        # Clear the service token to prevent new connections from being made.
        service_token.clear_service_token()

        self._client.send(
            inform_teardown=spb.ServerInformTeardownRequest(
                exit_code=exit_code,
            )
        )

        return self._proc.join()
