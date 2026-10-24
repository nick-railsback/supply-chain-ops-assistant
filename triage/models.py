"""The stuck-order case record: a self-contained snapshot a triager can read."""

from datetime import datetime

from pydantic import BaseModel

from models.oms import LineItem, Order, OrderException
from models.tms import Shipment
from models.wms import InventoryItem
from triage.taxonomy import RootCause


class TriageCase(BaseModel):
    case_id: str
    as_of: datetime
    label: RootCause
    order: Order
    line_items: list[LineItem]
    exceptions: list[OrderException]
    shipment: Shipment | None = None
    inventory: list[InventoryItem]
