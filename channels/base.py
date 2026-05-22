from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SendResult:
    success: bool
    external_id: Optional[str] = None
    error: Optional[str] = None


@dataclass
class PastePayload:
    copy_text: str
    profile_url: Optional[str] = None
    mark_sent_endpoint: Optional[str] = None
    extra: dict = field(default_factory=dict)


class ChannelAdapter(ABC):
    @abstractmethod
    def supports_server_send(self) -> bool: ...

    @abstractmethod
    def send(self, tenant, prospect, message_text: str) -> SendResult: ...

    @abstractmethod
    def prepare_paste(self, tenant, prospect, message_text: str) -> PastePayload: ...
