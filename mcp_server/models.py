"""Response shape for get_order_triage_context.

Mirrors triage.models.TriageCase's non-label fields exactly, without
inheriting from it: TriageCase requires case_id, as_of, and label, and this
chunk's responses must never carry anything label-shaped.
"""

from pydantic import BaseModel

from models.oms import LineItem, Order, OrderException
from models.tms import Shipment
from models.wms import InventoryItem


class TriageContext(BaseModel):
    order: Order
    line_items: list[LineItem]
    exceptions: list[OrderException]
    shipment: Shipment | None
    inventory: list[InventoryItem]
