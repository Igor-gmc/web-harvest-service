import enum


class TaskType(str, enum.Enum):
    fedresurs = "fedresurs"
    kad_arbitr = "kad_arbitr"


class TaskStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    resume_pending = "resume_pending"
    retry_scheduled = "retry_scheduled"
    done = "done"
    not_found = "not_found"
    failed = "failed"


class ProxyStatus(str, enum.Enum):
    active = "active"
    cooldown = "cooldown"
    disabled = "disabled"


class ErrorType(str, enum.Enum):
    temporary = "temporary"
    proxy = "proxy"
    captcha = "captcha"
    not_found = "not_found"
    unknown = "unknown"


class CheckpointStep(str, enum.Enum):
    init = "init"
    started = "started"
    search_submitted = "search_submitted"
    result_found = "result_found"
    card_opened = "card_opened"
    tab_opened = "tab_opened"
    data_extracted = "data_extracted"
