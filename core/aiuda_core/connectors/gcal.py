"""Conector Google Calendar — citas y disponibilidad (REST v3).

Para qué lo usa aiuda: Valeria (recepción) agenda citas respetando la
disponibilidad real, y Mariana agenda llamadas de cobranza acordadas.

Auth: bearer token ya emitido (OAuth del negocio o service account con domain
delegation). El flujo de consentimiento vive en el onboarding del cloud; este
cliente solo consume el token.
"""

from dataclasses import dataclass
from datetime import datetime

import httpx

from aiuda_core.config import settings

BASE_URL = "https://www.googleapis.com/calendar/v3"


@dataclass
class CalendarEvent:
    id: str
    summary: str
    start: str
    end: str
    html_link: str


class GoogleCalendarClient:
    def __init__(
        self,
        token: str | None = None,
        calendar_id: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.token = token or settings.google_calendar_token
        if not self.token:
            raise RuntimeError("GOOGLE_CALENDAR_TOKEN no configurado — ver .env.example")
        self.calendar_id = calendar_id or settings.google_calendar_id
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=30,
            transport=transport,
        )

    def busy_slots(self, time_min: datetime, time_max: datetime) -> list[dict]:
        """Bloques ocupados — para nunca agendar encima de algo."""
        response = self._http.post(
            "/freeBusy",
            json={
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "items": [{"id": self.calendar_id}],
            },
        )
        response.raise_for_status()
        calendars = response.json().get("calendars", {})
        return calendars.get(self.calendar_id, {}).get("busy", [])

    def list_events(
        self, time_min: datetime | None = None, max_results: int = 50
    ) -> list[CalendarEvent]:
        """Próximos eventos del calendario — la agenda que lee aiuda (capacidad
        `agenda`). Expande recurrencias (singleEvents) y ordena por inicio. Soporta
        eventos con hora y de día completo (start.date)."""
        params: dict = {
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": max_results,
        }
        if time_min is not None:
            params["timeMin"] = time_min.isoformat()
        response = self._http.get(
            f"/calendars/{self.calendar_id}/events", params=params
        )
        response.raise_for_status()
        eventos = []
        for ev in response.json().get("items", []):
            start = ev.get("start") or {}
            end = ev.get("end") or {}
            eventos.append(
                CalendarEvent(
                    id=ev["id"],
                    summary=ev.get("summary", ""),
                    start=start.get("dateTime") or start.get("date") or "",
                    end=end.get("dateTime") or end.get("date") or "",
                    html_link=ev.get("htmlLink", ""),
                )
            )
        return eventos

    def test_connection(self) -> dict:
        """Prueba ligera para 'Probar conexión': valida el token listando los
        calendarios visibles (calendarList) sin traer eventos, y confirma que el
        calendario configurado esté entre ellos (si no, el ID o los permisos están
        mal y la agenda quedaría vacía en silencio)."""
        response = self._http.get(
            "/users/me/calendarList", params={"maxResults": 250}
        )
        response.raise_for_status()
        items = response.json().get("items", [])
        ids = {c.get("id") for c in items}
        return {
            "calendarios": len(items),
            "calendario_configurado": self.calendar_id,
            "configurado_visible": self.calendar_id in ids,
        }

    def create_event(
        self, summary: str, start: datetime, end: datetime, description: str = ""
    ) -> CalendarEvent:
        response = self._http.post(
            f"/calendars/{self.calendar_id}/events",
            json={
                "summary": summary,
                "description": description,
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": end.isoformat()},
            },
        )
        response.raise_for_status()
        data = response.json()
        return CalendarEvent(
            id=data["id"],
            summary=data.get("summary", summary),
            start=data["start"]["dateTime"],
            end=data["end"]["dateTime"],
            html_link=data.get("htmlLink", ""),
        )
