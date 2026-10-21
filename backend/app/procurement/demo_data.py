"""
Worked examples for the procurement module, so the screens can be read.

Empty screens do not explain themselves. This builds seven requirements that
between them sit in every state the module has — waiting for approval, ready
to order, part-received, afloat, costed, closed — so each button can be seen
in the situation it is for.

    python -m app.procurement.demo_data                 # show what it would do
    python -m app.procurement.demo_data --apply         # create it
    python -m app.procurement.demo_data --remove        # take it all back out

Everything is created through the real API, so the data obeys exactly the
same rules as anything typed in by hand — a demo order that could not have
been entered would teach the wrong thing.

Two of these post goods receipts, which **adds stock**. The quantities and
the resulting company total are printed, and `--remove` reverses them
exactly: every id created is written to a manifest under data/backups, and
removal deletes what that file lists and nothing else.
"""

import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.companies.models import Company
from app.inventory.models import InventoryItem, ItemLocation
from app.main import app

API = "/api/v1"
MANIFEST = Path("data/backups/demo_procurement.json")

# Suppliers a Faisalabad textile-machinery dealer would actually buy from:
# three local, three abroad, in the currencies each really invoices in.
SUPPLIERS = [
    {
        "code": "SUP-HITECH", "name": "Hi-Tech Engineering Works",
        "city": "Faisalabad", "country": "Pakistan", "currency": "PKR",
        "address": "Plot 42, Small Industrial Estate, Sargodha Road, Faisalabad",
        "phone": "041-8735120", "ntn": "3124567-8",
        "payment_terms": "30 days", "credit_days": 30, "is_international": False,
    },
    {
        "code": "SUP-CRESCENT", "name": "Crescent Bearings & Seals",
        "city": "Lahore", "country": "Pakistan", "currency": "PKR",
        "address": "18-A Badami Bagh, Circular Road, Lahore",
        "phone": "042-37662840", "ntn": "0918273-4",
        "payment_terms": "15 days", "credit_days": 15, "is_international": False,
    },
    {
        "code": "SUP-PIS", "name": "Pak Industrial Supplies",
        "city": "Karachi", "country": "Pakistan", "currency": "PKR",
        "address": "Office 6, Techno City, I.I. Chundrigar Road, Karachi",
        "phone": "021-32412900", "ntn": "1276543-1",
        "payment_terms": "Advance", "credit_days": 0, "is_international": False,
    },
    {
        "code": "SUP-SHTEX", "name": "Shanghai Textile Machinery Parts Co. Ltd",
        "city": "Shanghai", "country": "China", "country_of_origin": "China",
        "currency": "USD", "incoterm": "FOB",
        "address": "No. 888 Songze Avenue, Qingpu District, Shanghai 201703, China",
        "phone": "+86 21 6958 4400",
        "bank_name": "Bank of China, Shanghai Branch",
        "bank_swift": "BKCHCNBJ300", "bank_iban": "CN11 3020 0001 2345 6789",
        "payment_terms": "LC at sight", "is_international": True,
    },
    {
        "code": "SUP-OROX", "name": "Orox Cutting Systems S.r.l.",
        "city": "Biella", "country": "Italy", "country_of_origin": "Italy",
        "currency": "EUR", "incoterm": "CIF",
        "address": "Via Pietro Micca 14, 13900 Biella (BI), Italy",
        "phone": "+39 015 840 1200",
        "bank_name": "Intesa Sanpaolo S.p.A.",
        "bank_swift": "BCITITMM", "bank_iban": "IT60 X054 2811 1010 0000 0123 456",
        "payment_terms": "50% advance, 50% against BL", "is_international": True,
    },
    {
        "code": "SUP-TKT", "name": "TKT Plottertechnik GmbH",
        "city": "Krefeld", "country": "Germany", "country_of_origin": "Germany",
        "currency": "EUR", "incoterm": "EXW",
        "address": "Industriestrasse 27, 47809 Krefeld, Germany",
        "phone": "+49 2151 93780",
        "bank_name": "Commerzbank AG", "bank_swift": "COBADEFF",
        "payment_terms": "TT in advance", "is_international": True,
    },
]

#: Charges on the two costed imports, keyed by the seeded charge type name.
#: Amounts are in PKR, which is how a Pakistani importer settles all of them
#: except the ocean freight a forwarder sometimes bills in dollars.
SEA_IMPORT_CHARGES = [
    ("Customs Duty", "1120000"),
    ("Regulatory Duty", "185000"),
    ("Sales Tax", "742000"),
    ("Additional Sales Tax", "128000"),
    ("Port Charges", "96500"),
    ("Terminal Handling", "64000"),
    ("Clearing Agent Charges", "135000"),
    ("Documentation Charges", "18500"),
    ("LC Charges", "72000"),
    ("Bank Charges", "24500"),
    ("Inland Freight", "88000"),
]

AIR_IMPORT_CHARGES = [
    ("Customs Duty", "268000"),
    ("Sales Tax", "171000"),
    ("Clearing Agent Charges", "46000"),
    ("Examination Charges", "12500"),
    ("Bank Charges", "18000"),
]


def money(value) -> str:
    return f"{Decimal(str(value)):,.2f}"


class Seeder:
    def __init__(self, client: TestClient, db, apply: bool):
        self.c = client
        self.db = db
        self.apply = apply
        self.made: dict[str, list] = {
            "partners": [], "in_house_orders": [], "purchase_orders": [],
            "shipments": [], "landed_costs": [], "goods_receipts": [],
        }
        self.notes: list[str] = []

    # ---------------------------------------------------------------- helpers

    def post(self, path: str, payload: dict, expect: int = 201) -> dict:
        r = self.c.post(f"{API}{path}", json=payload)
        if r.status_code != expect:
            raise RuntimeError(f"POST {path} -> {r.status_code}: {str(r.json())[:400]}")
        return r.json()

    def status(self, path: str, value: str) -> dict:
        r = self.c.post(f"{API}{path}/status", json={"status": value})
        if r.status_code != 200:
            raise RuntimeError(f"{path} -> {value}: {r.status_code} {str(r.json())[:400]}")
        return r.json()

    def supplier(self, code: str) -> str:
        return self.suppliers[code]

    def note(self, text: str) -> None:
        self.notes.append(text)
        print(f"    {text}")

    # --------------------------------------------------------------- products

    def pick_products(self) -> None:
        """Real products from the catalogue, grouped the way a buyer would
        actually order them — one purchase per machine family."""
        def by_family(family: str, limit: int) -> list[dict]:
            rows = self.db.execute(text("""
                select i.id, i.item_code, i.description, i.uom
                from inventory_items i
                join inventory_sub_detail_categories d
                  on d.id = i.sub_detail_category_id
                where d.description = :family
                  and length(i.description) between 15 and 60
                order by i.item_code
                limit :limit
            """), {"family": family, "limit": limit}).all()
            return [
                {"id": str(r.id), "item_code": r.item_code,
                 "description": r.description, "uom": r.uom or "PCS"}
                for r in rows
            ]

        self.products = {
            "gerber": by_family("GERBER CUTTER", 4),
            "orox": by_family("OROX CUTTER", 3),
            "plotter": by_family("TKT PLOTTER", 3),
            "knife": by_family("KNIFE GROUP", 3),
            "movement": by_family("MAIN MOVEMENT GROUP", 3),
        }
        missing = [k for k, v in self.products.items() if not v]
        if missing:
            raise RuntimeError(f"No products found for: {', '.join(missing)}")

    # -------------------------------------------------------------- suppliers

    def make_suppliers(self) -> None:
        print("\n  Suppliers")
        self.suppliers = {}
        for spec in SUPPLIERS:
            existing = self.db.scalar(text(
                "select id from business_partners where code = :code"),
                {"code": spec["code"]})
            if existing:
                self.suppliers[spec["code"]] = str(existing)
                self.note(f"{spec['name']} — already there, left alone")
                continue
            if not self.apply:
                self.suppliers[spec["code"]] = "(dry run)"
                self.note(f"{spec['name']} ({spec['country']}, "
                          f"{spec['currency']}) — would create")
                continue
            row = self.post("/partners", {
                **spec, "is_customer": False, "is_supplier": True, "is_active": True,
            })
            self.suppliers[spec["code"]] = row["id"]
            self.made["partners"].append(row["id"])
            self.note(f"{spec['name']} ({spec['country']}, {spec['currency']})")

    # ------------------------------------------------------------ requirement

    def requirement(self, *, warehouse: str, requested_by: str, purpose: str,
                    source: str, priority: str, products: list[dict],
                    quantities: list, fulfilment: str, days_out: int = 21) -> dict:
        lines = [
            {
                "item_id": product["id"],
                "requested_quantity": str(quantity),
                "fulfilment_source": fulfilment,
            }
            for product, quantity in zip(products, quantities)
        ]
        return self.post("/procurement/in-house-orders", {
            "doc_date": str(date.today() - timedelta(days=days_out)),
            "warehouse_id": self.warehouses[warehouse],
            "requested_by": requested_by,
            "department": "Stores",
            "required_date": str(date.today() + timedelta(days=14)),
            "priority": priority,
            "source": source,
            "purpose": purpose,
            "lines": lines,
        })

    def approve_requirement(self, iho: dict) -> None:
        self.status(f"/procurement/in-house-orders/{iho['id']}", "Submitted")
        self.status(f"/procurement/in-house-orders/{iho['id']}", "Approved")

    def order_from(self, iho: dict, *, supplier_code: str, purchase_type: str,
                   currency: str, rate: str, prices: list[str],
                   fraction: Decimal = Decimal("1")) -> dict:
        """Raise a purchase order for part or all of a requirement."""
        outstanding = self.c.get(
            f"{API}/procurement/in-house-orders/{iho['id']}/outstanding").json()
        lines = []
        for line, price in zip(outstanding["lines"], prices):
            quantity = (Decimal(str(line["outstanding_quantity"])) * fraction
                        ).quantize(Decimal("1"))
            if quantity <= 0:
                continue
            lines.append({"line_id": line["line_id"], "quantity": str(quantity),
                          "unit_price": price, "tax_percent": "18"})
        order = self.post(
            f"/procurement/in-house-orders/{iho['id']}/purchase-orders", {
                "purchase_type": purchase_type,
                "supplier_id": self.supplier(supplier_code),
                "doc_date": str(date.today() - timedelta(days=17)),
                "currency": currency,
                "exchange_rate": rate,
                "warehouse_id": iho.get("warehouse_id"),
                "lines": lines,
            })
        self.made["purchase_orders"].append(order["id"])
        self.status(f"/procurement/purchase-orders/{order['id']}", "Approved")
        return order

    # ---------------------------------------------------------------- receipt

    def receive(self, *, order: dict | None = None, shipment: dict | None = None,
                fraction: Decimal, invoice: str, post_it: bool = True,
                landed_cost_id: str | None = None, days_ago: int = 3) -> dict:
        query = (f"shipment_id={shipment['id']}" if shipment
                 else f"purchase_order_id={order['id']}")
        source = self.c.get(f"{API}/procurement/receivable?{query}").json()

        lines = []
        for line in source["lines"]:
            outstanding = Decimal(str(line["outstanding_quantity"]))
            if outstanding <= 0:
                continue
            quantity = (outstanding * fraction).quantize(Decimal("1")) or Decimal("1")
            lines.append({
                "purchase_order_line_id": line.get("purchase_order_line_id"),
                "shipment_line_id": line.get("shipment_line_id"),
                "item_id": line["item_id"],
                "item_code": line["item_code"],
                "description": line["description"],
                "uom": line["uom"],
                "ordered_quantity": str(line["ordered_quantity"]),
                "received_quantity": str(quantity),
                "unit_price": str(line["unit_price"]),
                "tax_percent": "18",
            })
        if not lines:
            raise RuntimeError("nothing outstanding to receive")

        grn = self.post("/procurement/goods-receipts", {
            "doc_date": str(date.today() - timedelta(days=days_ago)),
            "supplier_id": source["supplier_id"],
            "purchase_order_id": source["purchase_order_id"],
            "shipment_id": source.get("shipment_id"),
            "landed_cost_id": landed_cost_id or source.get("landed_cost_id"),
            "warehouse_id": source["warehouse_id"] or self.warehouses["JEZ FSD"],
            "supplier_invoice_number": invoice,
            "supplier_invoice_date": str(date.today() - timedelta(days=days_ago + 1)),
            "vehicle_number": "FDB-1147" if not shipment else None,
            "received_by": "Store Keeper",
            "currency": source["currency"],
            "exchange_rate": str(source["exchange_rate"]),
            "lines": lines,
        })
        self.made["goods_receipts"].append(grn["id"])
        if post_it:
            self.status(f"/procurement/goods-receipts/{grn['id']}", "Posted")
        return grn

    # --------------------------------------------------------------- shipment

    def ship(self, order: dict, *, container: str | None, bl: str | None,
             awb: str | None, mode: str, loading: str, vessel: str | None,
             freight: str, insurance: str, days_out: int,
             agent: str = "Al-Rehman Clearing & Forwarding") -> dict:
        detail = self.c.get(f"{API}/procurement/purchase-orders/{order['id']}").json()
        lines = [
            {
                "purchase_order_line_id": line["id"],
                "item_code": line["item_code"],
                "description": line["description"],
                "uom": line["uom"],
                "shipped_quantity": str(line["quantity"]),
                "unit_price": str(line["unit_price"]),
                # Weight is what ocean freight is spread by, so a demo that
                # omits it would show an even split and teach the wrong thing.
                "total_weight": str(Decimal(str(line["quantity"])) * Decimal("1.8")),
            }
            for line in detail["lines"]
        ]
        shipment = self.post("/procurement/shipments", {
            "doc_date": str(date.today() - timedelta(days=days_out)),
            "purchase_order_id": order["id"],
            "warehouse_id": self.warehouses["JEZ FSD"],
            "currency": detail["currency"],
            "exchange_rate": str(detail["exchange_rate"]),
            "container_number": container,
            "bill_of_lading_number": bl,
            "airway_bill_number": awb,
            "vessel_or_flight": vessel,
            "port_of_loading": loading,
            "port_of_discharge": "Karachi Port" if mode == "Sea"
                                 else "Jinnah International Airport",
            "shipping_mode": mode,
            "clearing_agent": agent,
            "etd": str(date.today() - timedelta(days=days_out)),
            "eta": str(date.today() - timedelta(days=max(1, days_out - 22))),
            "freight_amount": freight,
            "insurance_amount": insurance,
            "lines": lines,
        })
        self.made["shipments"].append(shipment["id"])
        return shipment

    def move_shipment(self, shipment: dict, upto: str) -> None:
        flow = ["Booked", "Shipped", "In Transit", "Arrived",
                "Customs Pending", "Customs Cleared"]
        for step in flow:
            self.status(f"/procurement/shipments/{shipment['id']}", step)
            if step == upto:
                return

    # ------------------------------------------------------------ landed cost

    def cost(self, shipment: dict, charges: list[tuple[str, str]],
             *, post_it: bool) -> dict:
        voucher = self.post(
            f"/procurement/shipments/{shipment['id']}/landed-cost",
            {"doc_date": str(date.today() - timedelta(days=5)),
             "allocation_method": "Value", "include_shipment_charges": True})
        self.made["landed_costs"].append(voucher["id"])

        types = {t["name"]: t for t in
                 self.c.get(f"{API}/procurement/charge-types").json()["items"]}
        rows = list(voucher["charges"])
        for name, amount in charges:
            charge_type = types.get(name)
            if charge_type is None:
                continue
            rows.append({
                "charge_type_id": charge_type["id"], "name": name,
                "cost_group": charge_type["cost_group"],
                "currency": "PKR", "exchange_rate": "1", "amount": amount,
                "allocation_method": charge_type["default_allocation"],
            })

        r = self.c.put(f"{API}/procurement/landed-costs/{voucher['id']}", json={
            "doc_date": voucher["doc_date"],
            "purchase_order_id": voucher["purchase_order_id"],
            "shipment_id": voucher["shipment_id"],
            "supplier_id": voucher["supplier_id"],
            "currency": voucher["currency"],
            "exchange_rate": str(voucher["exchange_rate"]),
            "allocation_method": "Value",
            "supplier_invoice_number": voucher["supplier_invoice_number"],
            "charges": rows,
            "items": [
                {
                    "id": item["id"],
                    "shipment_line_id": item["shipment_line_id"],
                    "purchase_order_line_id": item["purchase_order_line_id"],
                    "item_id": item["item_id"],
                    "item_code": item["item_code"],
                    "description": item["description"],
                    "uom": item["uom"],
                    "quantity": str(item["quantity"]),
                    "unit_price": str(item["unit_price"]),
                    "total_weight": (str(item["total_weight"])
                                     if item["total_weight"] else None),
                }
                for item in voucher["items"]
            ],
        })
        if r.status_code != 200:
            raise RuntimeError(f"costing: {r.status_code} {str(r.json())[:300]}")
        costed = r.json()

        if post_it:
            for step in ("Pending Approval", "Approved", "Posted"):
                self.status(f"/procurement/landed-costs/{costed['id']}", step)
            costed = self.c.get(
                f"{API}/procurement/landed-costs/{costed['id']}").json()
        return costed

    # ------------------------------------------------------------------- build

    def run(self) -> None:
        company_id = self.db.scalar(select(Company.id).order_by(Company.created_at))
        self.warehouses = {
            row.location: str(row.id)
            for row in self.db.scalars(select(ItemLocation).where(
                ItemLocation.company_id == company_id)).all()
        }
        self.pick_products()
        self.make_suppliers()

        if not self.apply:
            print("\n  Seven requirements would be created, covering every state:")
            for line in (
                "1  Gerber cutter spares — local, received in two deliveries, closed",
                "2  Knife group parts   — local, part-received, rest outstanding",
                "3  Movement group      — local, waiting for approval",
                "4  Orox spares         — import from Italy, afloat (goods in transit)",
                "5  Gerber blades bulk  — import from China, costed, posted, received",
                "6  TKT plotter parts   — import from Germany by air, costing in progress",
                "7  Gerber consumables  — approved, waiting to be ordered",
            ):
                print(f"    {line}")
            return

        print("\n  1. Gerber cutter spares — local, two deliveries, closed")
        iho = self.requirement(
            warehouse="JEZ FSD", requested_by="Workshop Supervisor",
            purpose="Routine spares for the Gerber S-93 cutter under service contract",
            source="Stock Shortage", priority="High",
            products=self.products["gerber"][:3], quantities=[12, 8, 6],
            fulfilment="Local Purchase", days_out=24)
        self.made["in_house_orders"].append(iho["id"])
        self.approve_requirement(iho)
        order = self.order_from(iho, supplier_code="SUP-HITECH", purchase_type="Local",
                                currency="PKR", rate="1",
                                prices=["18500", "24750", "9200"])
        self.receive(order=order, fraction=Decimal("0.6"),
                     invoice="HTE-2026-0418", days_ago=9)
        self.receive(order=order, fraction=Decimal("1"),
                     invoice="HTE-2026-0451", days_ago=3)
        self.note(f"{iho['doc_number']} -> {order['doc_number']} -> two posted receipts")

        print("\n  2. Knife group parts — local, part received")
        iho = self.requirement(
            warehouse="JEZ FSD", requested_by="Ali Raza",
            purpose="Knife assembly wear parts for the Sialkot customer contract",
            source="Sales Demand", priority="Normal",
            products=self.products["knife"][:3], quantities=[20, 15, 10],
            fulfilment="Local Purchase", days_out=19)
        self.made["in_house_orders"].append(iho["id"])
        self.approve_requirement(iho)
        order = self.order_from(iho, supplier_code="SUP-CRESCENT", purchase_type="Local",
                                currency="PKR", rate="1",
                                prices=["3450", "6800", "12400"])
        self.receive(order=order, fraction=Decimal("0.5"),
                     invoice="CBS-4471", days_ago=5)
        self.note(f"{iho['doc_number']} -> {order['doc_number']} -> half received, "
                  "the rest still outstanding")

        print("\n  3. Main movement group — waiting for approval")
        iho = self.requirement(
            warehouse="M.Wasim FSD", requested_by="M. Wasim",
            purpose="Movement group overhaul kit — minimum level reached",
            source="Reorder", priority="Urgent",
            products=self.products["movement"][:3], quantities=[6, 4, 4],
            fulfilment="Local Purchase", days_out=4)
        self.made["in_house_orders"].append(iho["id"])
        self.status(f"/procurement/in-house-orders/{iho['id']}", "Submitted")
        self.note(f"{iho['doc_number']} — submitted, sitting on the approver")

        print("\n  4. Orox spares — import from Italy, still afloat")
        iho = self.requirement(
            warehouse="JEZ FSD", requested_by="Purchase Officer",
            purpose="Orox cutter spares not available locally",
            source="Stock Shortage", priority="Normal",
            products=self.products["orox"][:3], quantities=[10, 6, 6],
            fulfilment="Import Purchase", days_out=40)
        self.made["in_house_orders"].append(iho["id"])
        self.approve_requirement(iho)
        order = self.order_from(iho, supplier_code="SUP-OROX", purchase_type="Import",
                                currency="EUR", rate="312.40",
                                prices=["148.50", "96.00", "212.75"])
        shipment = self.ship(order, container="MSCU-7741208", bl="MSCUIT2600841",
                             awb=None, mode="Sea", loading="Genoa",
                             vessel="MSC ANTONIA / 442W", freight="410000",
                             insurance="68000", days_out=12)
        self.move_shipment(shipment, "In Transit")
        self.note(f"{order['doc_number']} -> {shipment['doc_number']} — in transit, "
                  "counted as goods in transit and not as warehouse stock")

        print("\n  5. Gerber blades — import from China, costed and received")
        iho = self.requirement(
            warehouse="JEZ FSD", requested_by="Purchase Officer",
            purpose="Bulk blade and sensor stock for the year",
            source="Reorder", priority="Normal",
            products=self.products["gerber"][:2] + self.products["plotter"][:1],
            quantities=[600, 250, 120], fulfilment="Import Purchase", days_out=75)
        self.made["in_house_orders"].append(iho["id"])
        self.approve_requirement(iho)
        order = self.order_from(iho, supplier_code="SUP-SHTEX", purchase_type="Import",
                                currency="USD", rate="279.50",
                                prices=["18.40", "42.75", "31.20"])
        shipment = self.ship(order, container="TCLU-9938471", bl="COSU6398471200",
                             awb=None, mode="Sea", loading="Shanghai",
                             vessel="COSCO HAIFA / 018E", freight="565000",
                             insurance="94000", days_out=48)
        self.move_shipment(shipment, "Customs Cleared")
        voucher = self.cost(shipment, SEA_IMPORT_CHARGES, post_it=True)
        self.note(f"{voucher['doc_number']} posted — goods "
                  f"PKR {money(voucher['purchase_cost_base'])} + import costs "
                  f"PKR {money(voucher['additional_cost_base'])} = "
                  f"PKR {money(voucher['total_landed_cost'])} "
                  f"({voucher['additional_cost_percent']}% on top)")
        for item in voucher["items"][:3]:
            self.note(f"   {item['item_code']}: bought at "
                      f"{money(item['unit_purchase_cost'])}, "
                      f"landed at {money(item['unit_landed_cost'])} per "
                      f"{item['uom'] or 'unit'}")
        self.receive(shipment=shipment, fraction=Decimal("1"),
                     invoice="SHTEX-INV-26/0774",
                     landed_cost_id=voucher["id"], days_ago=2)
        self.note("received into JEZ FSD at the landed unit cost, not the supplier price")

        print("\n  6. TKT plotter parts — import from Germany by air, costing open")
        iho = self.requirement(
            warehouse="JEZ FSD", requested_by="Service Engineer",
            purpose="Urgent plotter head parts for a machine down at the customer",
            source="Production", priority="Urgent",
            products=self.products["plotter"][:3], quantities=[4, 4, 2],
            fulfilment="Import Purchase", days_out=30)
        self.made["in_house_orders"].append(iho["id"])
        self.approve_requirement(iho)
        order = self.order_from(iho, supplier_code="SUP-TKT", purchase_type="Import",
                                currency="EUR", rate="311.80",
                                prices=["685.00", "412.50", "1180.00"])
        shipment = self.ship(order, container=None, bl=None, awb="020-84471963",
                             mode="Air", loading="Dusseldorf",
                             vessel="EK 9842", freight="238000",
                             insurance="31000", days_out=9,
                             agent="Sky Cargo Services (Pvt) Ltd")
        self.move_shipment(shipment, "Customs Cleared")
        voucher = self.cost(shipment, AIR_IMPORT_CHARGES, post_it=False)
        self.note(f"{voucher['doc_number']} left at Cost Entry — open to edit, and the "
                  "receipt screen will refuse to post until it is")

        print("\n  7. Gerber consumables — approved, waiting to be ordered")
        iho = self.requirement(
            warehouse="Saqib Ali Lahore", requested_by="Saqib Ali",
            purpose="Consumables for the Lahore stock point",
            source="Branch Request", priority="Normal",
            products=self.products["gerber"][1:4], quantities=[30, 25, 20],
            fulfilment="Local Purchase", days_out=6)
        self.made["in_house_orders"].append(iho["id"])
        self.approve_requirement(iho)
        self.note(f"{iho['doc_number']} — approved and pending procurement, ready for "
                  "the Order button")


def stock_total(db) -> Decimal:
    return Decimal(str(db.scalar(text(
        "select coalesce(sum(case when direction='in' then quantity "
        "else -quantity end), 0) from stock_ledger_entries")) or 0))


def remove(db) -> None:
    """Take out exactly what the manifest lists, and nothing else."""
    if not MANIFEST.exists():
        print(f"No manifest at {MANIFEST}. Nothing was seeded by this script, or it "
              "has already been removed.")
        return

    made = json.loads(MANIFEST.read_text(encoding="utf-8"))
    before = stock_total(db)

    grns = made.get("goods_receipts", [])
    lcs = made.get("landed_costs", [])
    ships = made.get("shipments", [])
    pos = made.get("purchase_orders", [])
    ihos = made.get("in_house_orders", [])
    partners = made.get("partners", [])

    if grns:
        db.execute(text("delete from stock_ledger_entries where source_id = any(:v)"),
                   {"v": grns})
        db.execute(text("delete from mrn_lines where mrn_id = any(:v)"), {"v": grns})
        db.execute(text("delete from material_receiving_notes where id = any(:v)"),
                   {"v": grns})
    if lcs:
        db.execute(text(
            "delete from landed_cost_allocations where landed_cost_item_id in "
            "(select id from landed_cost_items where landed_cost_id = any(:v))"),
            {"v": lcs})
        db.execute(text("delete from landed_cost_items where landed_cost_id = any(:v)"),
                   {"v": lcs})
        db.execute(text("delete from landed_cost_charges where landed_cost_id = any(:v)"),
                   {"v": lcs})
        db.execute(text("delete from landed_costs where id = any(:v)"), {"v": lcs})
    if ships:
        db.execute(text("delete from import_shipment_lines where shipment_id = any(:v)"),
                   {"v": ships})
        db.execute(text("delete from import_shipments where id = any(:v)"), {"v": ships})
    if pos:
        db.execute(text(
            "delete from purchase_order_lines where purchase_order_id = any(:v)"),
            {"v": pos})
        db.execute(text("delete from purchase_orders where id = any(:v)"), {"v": pos})
    if ihos:
        db.execute(text(
            "delete from in_house_order_lines where in_house_order_id = any(:v)"),
            {"v": ihos})
        db.execute(text("delete from in_house_orders where id = any(:v)"), {"v": ihos})
    if partners:
        db.execute(text("delete from business_partners where id = any(:v)"),
                   {"v": partners})
    db.commit()

    after = stock_total(db)
    print(f"  removed {len(ihos)} requirements, {len(pos)} purchase orders, "
          f"{len(ships)} shipments, {len(lcs)} costings, {len(grns)} receipts, "
          f"{len(partners)} suppliers")
    print(f"  company stock total {money(before)} -> {money(after)}")
    MANIFEST.unlink()
    print(f"  manifest {MANIFEST} deleted")


def main() -> None:
    apply = "--apply" in sys.argv
    db = SessionLocal()
    try:
        if "--remove" in sys.argv:
            print("REMOVING the demo procurement data\n")
            remove(db)
            return

        print("APPLYING" if apply else "DRY RUN — nothing will be written")
        before = stock_total(db)

        if apply and MANIFEST.exists():
            print(f"\n{MANIFEST} already exists, so this has been seeded before. "
                  "Run with --remove first if you want a clean set.")
            return

        seeder = Seeder(TestClient(app), db, apply)
        seeder.run()

        if apply:
            MANIFEST.parent.mkdir(parents=True, exist_ok=True)
            MANIFEST.write_text(json.dumps(seeder.made, indent=2), encoding="utf-8")
            after = stock_total(db)
            print(f"\n  company stock total {money(before)} -> {money(after)} "
                  f"(+{money(after - before)} from the two posted receipts)")
            print(f"  manifest written to {MANIFEST}")
            print("\nRun with --remove to take all of it back out, including the "
                  "stock it added.")
        else:
            print("\nNothing written. Re-run with --apply to create it.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
