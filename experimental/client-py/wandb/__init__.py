"""wandb library."""

__version__ = "0.0.1.dev1"

import time
from wandb.proto import wandb_internal_pb2 as pb2


class Api:
    def __init__(self):
        self._obj = None

    @property
    def _api(self):
        return self._obj

    def new_session(self) -> "Session":
        return Session(_api=self)

    def teardown(self):
        pass


def new_api():
    return Api()


class Image:
    def __init__(self, data):
        self._data = data


# global library object
default_api = new_api()
default_session = None
default_entity = None
default_project = None
default_group = None
default_run = None


class Session:
    def __init__(self, _api):
        self.__api = _api
        self._loaded = False
        self._last_run = None

    @property
    def _api(self):
        return self.__api._api

    def _ensure_loaded(self):
        if self._loaded:
            return
        from wandb import service
        s = service._Service(None)
        s.start()
        # self._api.pbSessionSetup()
        self._loaded = True

    def configure_auth(self):
        self._ensure_loaded()
        pass

    def login(self):
        self._ensure_loaded()
        pass

    def new_run(self) -> "Run":
        self._ensure_loaded()
        run = Run(_session=self)
        run._start()
        self._last_run = run
        return run

    def teardown(self):
        pass


def new_session() -> Session:
    return default_api.new_session()


class Run:
    def __init__(self, _session):
        self._session = _session
        self._run_nexus_id = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.finish()

    @property
    def _api(self):
        return self._session._api

    def log(self, data):
        data_msg = pb2.HistoryRecord()
        for k, v in data.items():
            item = data_msg.item.add()
            item.key = k
            d = pb2.DataValue()
            if isinstance(v, int):
                d.value_int = v
            elif isinstance(v, float):
                d.value_double = v
            elif isinstance(v, str):
                d.value_string = v
            elif isinstance(v, Image):
                tensor_msg = pb2.TensorData()
                tensor_msg.tensor_content = v._data.tobytes()
                tensor_msg.shape.extend(v._data.shape)
                # TODO: see if we can do this without the CopyFrom
                d.value_tensor.CopyFrom(tensor_msg)
            # TODO: see if we can do this without the CopyFrom
            item.value_data.CopyFrom(d)

        data_bytes = data_msg.SerializeToString()
        self._api.pbRunLog(self._run_nexus_id, data_bytes, len(data_bytes))

    def _start(self):
        time.sleep(30)
        self._run_nexus_id = self._api.pbRunStart()

    def finish(self):
        self._api.pbRunFinish(self._run_nexus_id)

    @property
    def id(self):
        pass


# global default session object
default_session = new_session()


# ---
# wandb 0.x Compatibility
# ---


def require(_):
    pass


def setup():
    default_session._ensure_loaded()


def init(*args, **kwargs):
    return default_session.new_run()


def log(*args, **kwargs):
    default_session._last_run.log(*args, **kwargs)


def teardown():
    global _session
    _session = None
