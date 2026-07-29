"""Etiquetas del negocio: un administrador simple y asignación a registros.

Las definiciones viven en tenant.config["tags"] (sin migración) como
[{id, name, color}]. Cada registro guarda los ids en su columna `tags`
(hoy Customer; el patrón se extiende a otros registros después).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from aiuda_server.api.deps import get_db, get_tenant
from aiuda_core.models import Customer, Tenant

router = APIRouter()

PALETTE = ["azul", "verde", "ambar", "rojo", "morado", "rosa", "gris"]


def _tags(tenant: Tenant) -> list[dict]:
    return list((tenant.config or {}).get("tags") or [])


def _save_tags(db, tenant: Tenant, tags: list[dict]) -> None:
    tenant.config = {**(tenant.config or {}), "tags": tags}
    db.add(tenant)
    db.flush()


class TagBody(BaseModel):
    name: str
    color: str | None = None


@router.get("/v1/tags")
def list_tags(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    tags = _tags(tenant)
    customers = db.scalars(select(Customer).where(Customer.tenant_id == tenant.id)).all()
    counts: dict[str, int] = {}
    for c in customers:
        for tid in c.tags or []:
            counts[tid] = counts.get(tid, 0) + 1
    return [{**t, "count": counts.get(t["id"], 0)} for t in tags]


@router.post("/v1/tags", status_code=201)
def create_tag(body: TagBody, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="La etiqueta necesita un nombre.")
    tags = _tags(tenant)
    if any(t["name"].lower() == name.lower() for t in tags):
        raise HTTPException(status_code=409, detail="Ya existe una etiqueta con ese nombre.")
    color = body.color if body.color in PALETTE else PALETTE[len(tags) % len(PALETTE)]
    tag = {"id": uuid.uuid4().hex[:8], "name": name, "color": color}
    tags.append(tag)
    _save_tags(db, tenant, tags)
    return {**tag, "count": 0}


@router.put("/v1/tags/{tag_id}")
def update_tag(tag_id: str, body: TagBody, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    tags = _tags(tenant)
    tag = next((t for t in tags if t["id"] == tag_id), None)
    if tag is None:
        raise HTTPException(status_code=404, detail="Etiqueta no encontrada.")
    if body.name.strip():
        tag["name"] = body.name.strip()
    if body.color in PALETTE:
        tag["color"] = body.color
    _save_tags(db, tenant, tags)
    return tag


@router.delete("/v1/tags/{tag_id}")
def delete_tag(tag_id: str, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    tags = [t for t in _tags(tenant) if t["id"] != tag_id]
    _save_tags(db, tenant, tags)
    # Quita la etiqueta de todos los clientes que la tenían.
    for c in db.scalars(select(Customer).where(Customer.tenant_id == tenant.id)).all():
        if tag_id in (c.tags or []):
            c.tags = [t for t in c.tags if t != tag_id]
            db.add(c)
    db.flush()
    return {"removed": tag_id}


class CustomerTagsBody(BaseModel):
    tags: list[str]


@router.put("/v1/customers/{customer_id}/tags")
def set_customer_tags(
    customer_id: str,
    body: CustomerTagsBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    cust = db.scalar(
        select(Customer).where(Customer.tenant_id == tenant.id, Customer.id == customer_id)
    )
    if cust is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    valid = {t["id"] for t in _tags(tenant)}
    cust.tags = [t for t in body.tags if t in valid]
    db.add(cust)
    db.flush()
    return {"id": cust.id, "tags": cust.tags}
