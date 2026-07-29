"""Los teléfonos y tabletas que entran al mismo aiuda.

No son cuentas. No hay correo, ni contraseña, ni registro: son **aparatos
emparejados**. El dueño abre la pantalla de su equipo, aparece un QR, el otro lo
escanea y queda dentro. Y se saca igual de fácil.

Uno de ellos es el **mero mero**: el del dueño. Aprueba lo que sea, empareja a
los demás y los revoca. Los invitados entran al mismo ambiente con un papel más
chico: ver y proponer, o aprobar hasta cierto monto.

Del token solo se guarda su huella (SHA-256). Si alguien se lleva la base, no se
lleva las llaves de los teléfonos.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from aiuda_core.models.base import Base, TenantMixin, TimestampMixin, new_id

PAPELES = ("dueno", "invitado")


class Dispositivo(Base, TenantMixin, TimestampMixin):
    __tablename__ = "dispositivos"
    __table_args__ = (
        CheckConstraint("papel in ('dueno','invitado')", name="ck_dispositivo_papel"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # Como lo va a reconocer el dueño en su lista: "iPhone de Ana".
    nombre: Mapped[str] = mapped_column(String(80))
    papel: Mapped[str] = mapped_column(String(16), default="invitado", index=True)
    # Hasta cuánto puede aprobar un invitado por su cuenta. Vacío = no aprueba,
    # solo ve y propone. El mero mero ignora este tope.
    tope_aprobacion: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    # Huella del token, nunca el token.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ultimo_visto: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Revocar no borra: el dueño merece ver que ese aparato existió y cuándo salió.
    revocado_en: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def activo(self) -> bool:
        return self.revocado_en is None

    def puede_aprobar(self, monto: float | None = None) -> bool:
        """El mero mero aprueba lo que sea. El invitado, hasta su tope, y solo si
        tiene uno: sin tope no aprueba nada, ni siquiera lo chico."""
        if not self.activo:
            return False
        if self.papel == "dueno":
            return True
        if self.tope_aprobacion is None:
            return False
        if monto is None:
            return True
        return float(monto) <= float(self.tope_aprobacion)
