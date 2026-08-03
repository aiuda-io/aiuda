from aiuda_core.models.base import Base, TenantMixin, TimestampMixin, new_id, utcnow
from aiuda_core.models.observabilidad import Run, RunLink, RunTurn
from aiuda_core.models.entities import (
    AgentFeedback,
    Appointment,
    Ayudante,
    CfdiBoveda,
    Conversation,
    CuaMission,
    OptOut,
    OutboxEntry,
    Customer,
    Invoice,
    Message,
    Payment,
    PaymentPromise,
    Product,
    PurchaseOrder,
    Reminder,
    Tenant,
    UsageEvent,
    WhatsappChat,
)
from aiuda_core.models.dispositivos import Dispositivo
from aiuda_core.models.security import (
    AuditLog,
    IntegrationCredential,
)

__all__ = [
    "Base",
    "TenantMixin",
    "TimestampMixin",
    "new_id",
    "utcnow",
    "Tenant",
    "Customer",
    "Invoice",
    "Reminder",
    "Payment",
    "PaymentPromise",
    "Conversation",
    "OptOut",
    "Run",
    "RunLink",
    "RunTurn",
    "OutboxEntry",
    "Message",
    "WhatsappChat",
    "UsageEvent",
    "Product",
    "PurchaseOrder",
    "Appointment",
    "AgentFeedback",
    "Ayudante",
    "CuaMission",
    # La bóveda fiscal: cada CFDI del SAT, una vez (dedupe por UUID)
    "CfdiBoveda",
    # Los teléfonos y tabletas emparejados con este aiuda
    "Dispositivo",
    # Credenciales cifradas y auditoría local
    "IntegrationCredential",
    "AuditLog",
]
