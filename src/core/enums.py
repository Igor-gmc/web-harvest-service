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
    site_opened = "site_opened"
    search_submitted = "search_submitted"
    results_loaded = "results_loaded"
    card_opened = "card_opened"
    bankruptcy_found = "bankruptcy_found"
    data_extracted = "data_extracted"
    done = "done"
