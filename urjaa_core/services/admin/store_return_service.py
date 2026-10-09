"""Store returns against a POS bill -> credit note, stock back, refund.

Amount per returned unit = the line's charged price (final_price / quantity,
ex-GST, after the counter discount) + its GST share (3%, only if the bill
charged GST). Refund = value + GST - deduction. Returned quantity/value are
kept on the sale line (sales.returned_quantity / returned_amount): the DB
CHECK stops over-returns and Insights subtract returned_amount.
"""

from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from urjaa_core.models.custom_order import CustomOrder
from urjaa_core.models.custom_order_status import TERMINAL_STATUS_CODES, CustomOrderStatus
from urjaa_core.models.order import Order
from urjaa_core.models.product_variant import ProductVariant
from urjaa_core.models.sale import Sale
from urjaa_core.models.store_return import SaleReturn, SaleReturnLine, StoreCreditEntry
from urjaa_core.models.user import User
from urjaa_core.models.variant_physical_unit import VariantPhysicalUnit
from urjaa_core.repositories.admin.sales_repository import SalesRepository
from urjaa_core.schemas.admin.custom_orders import CustomOrderStatusUpdateRequest
from urjaa_core.schemas.admin.sales import SaleReturnCreateRequest
from urjaa_core.services import physical_unit_service
from urjaa_core.services.admin.custom_order_service import AdminCustomOrderService
from urjaa_core.services.admin.sales_service import (
    HSN_JEWELLERY,
    METHOD_LABELS,
    SalesService,
    ist_text,
    money,
    split_gst,
)

REASON_LABELS = {
    "defect": "Defect",
    "size": "Size",
    "changed_mind": "Changed mind",
    "exchange": "Exchange",
    "other": "Other",
}


def _store_bill(db: Session, store_id: UUID, order_id: UUID) -> Order:
    order = SalesRepository.get_order_by_id(db, order_id, store_id=store_id)
    if not order or order.source != "store" or not order.sale:
        raise HTTPException(status_code=404, detail="Store bill not found")
    return order


def _sold_pieces(db: Session, sale_id: UUID) -> list[VariantPhysicalUnit]:
    return (
        db.query(VariantPhysicalUnit)
        .filter(
            VariantPhysicalUnit.sale_id == sale_id,
            VariantPhysicalUnit.status_id == physical_unit_service._status_id(db, "sold"),
        )
        .order_by(VariantPhysicalUnit.id)
        .all()
    )


def _piece_label(unit: VariantPhysicalUnit) -> str:
    return unit.huid_number or unit.serial_number or f"Piece #{unit.id}"


def _open_alterations(db: Session, sale: Sale, order: Order) -> list[CustomOrder]:
    """Alteration orders for this line still in progress. Rows made before
    custom_orders.sale_id existed are matched by the product name in their notes."""
    product_name = sale.product.name if sale.product else ""
    return (
        db.query(CustomOrder)
        .join(CustomOrderStatus, CustomOrderStatus.id == CustomOrder.status_id)
        .filter(
            CustomOrder.sale_order_id == order.id,
            CustomOrderStatus.code.notin_(TERMINAL_STATUS_CODES),
            or_(
                CustomOrder.sale_id == sale.id,
                (CustomOrder.sale_id.is_(None)) & CustomOrder.design_notes.startswith(
                    f"Alteration — {product_name} (bill", autoescape=True
                ),
            ),
        )
        .all()
    )


def _next_credit_note_number(db: Session, store_id: UUID, when: datetime) -> str:
    # Same atomic per-(store, month) UPSERT as invoice numbers.
    period = when.strftime("%Y%m")
    seq = db.execute(
        text(
            """
            INSERT INTO credit_note_sequences (store_id, period, seq) VALUES (:store_id, :period, 1)
            ON CONFLICT (store_id, period) DO UPDATE SET seq = credit_note_sequences.seq + 1
            RETURNING seq
            """
        ),
        {"store_id": store_id, "period": period},
    ).scalar_one()
    return f"CN-{str(store_id).replace('-', '')[:8].upper()}-{period}-{seq}"


def get_return_info(db: Session, store_id: UUID, order_id: UUID) -> dict:
    order = _store_bill(db, store_id, order_id)
    sales = sorted(order.sale, key=lambda s: s.date_time)
    customer = next((s.customer for s in sales if s.customer), None)
    returns = db.query(SaleReturn).filter(SaleReturn.order_id == order.id).order_by(SaleReturn.id).all()
    lines = []
    for sale in sales:
        pieces = _sold_pieces(db, sale.id)
        lines.append(
            {
                "sale_id": sale.id,
                "product_name": sale.product.name if sale.product else "Unknown product",
                "sku_code": sale.variant.sku_code if sale.variant else None,
                "quantity": sale.quantity,
                "returned_quantity": sale.returned_quantity,
                "unit_price": float(money(Decimal(sale.final_price) / sale.quantity)),
                # Line total charged (ex-GST) and value already returned: the UI
                # works out the refund with the same rule as create_return.
                "final_price": float(sale.final_price),
                "returned_amount": float(sale.returned_amount),
                "tracked": bool(pieces),
                "pieces": [{"id": unit.id, "label": _piece_label(unit)} for unit in pieces],
                "alterations": [
                    {"id": co.id, "status_label": co.status.label} for co in _open_alterations(db, sale, order)
                ],
            }
        )
    return {
        "order_id": order.id,
        "invoice_number": order.invoice_number,
        "date_time": sales[0].date_time,
        "gst_charged": bool(order.tax_amount),
        "customer": (
            {
                "id": customer.id,
                "name": customer.full_name,
                "phone": customer.phone,
                "store_credit_balance": float(SalesService.store_credit_balance(db, customer.id)),
            }
            if customer
            else None
        ),
        "lines": lines,
        "returns": [
            {
                "id": r.id,
                "credit_note_number": r.credit_note_number,
                "refund_amount": float(r.refund_amount),
                "refund_method": r.refund_method,
                "created_at": r.created_at,
            }
            for r in returns
        ],
    }


def create_return(
    db: Session, store_id: UUID, order_id: UUID, payload: SaleReturnCreateRequest, admin_id: int | None
) -> dict:
    with SalesService._transaction_scope(db):
        order = _store_bill(db, store_id, order_id)
        bill_customer = next((s.customer for s in order.sale if s.customer), None)
        if len({line.sale_id for line in payload.lines}) != len(payload.lines):
            raise HTTPException(status_code=422, detail="Each item can be listed only once.")

        returned_lines: list[tuple[Sale, int, Decimal, list[str]]] = []
        for line in payload.lines:
            sale = (
                db.query(Sale)
                .filter(Sale.id == line.sale_id, Sale.order_id == order.id)
                .with_for_update()
                .first()
            )
            if sale is None:
                raise HTTPException(status_code=422, detail="An item is not on this bill.")
            name = sale.product.name if sale.product else "This item"
            left = sale.quantity - sale.returned_quantity
            if line.quantity > left:
                raise HTTPException(
                    status_code=422,
                    detail=f"{name}: only {left} of {sale.quantity} can still be returned.",
                )

            sold = {unit.id: unit for unit in _sold_pieces(db, sale.id)}
            pieces: list[str] = []
            if sold:
                if len(set(line.unit_ids)) != line.quantity or not set(line.unit_ids) <= sold.keys():
                    raise HTTPException(
                        status_code=422,
                        detail=f"{name}: pick exactly {line.quantity} of the pieces sold on this bill.",
                    )
                in_stock = physical_unit_service._status_id(db, "in_stock")
                for unit_id in line.unit_ids:
                    unit = sold[unit_id]
                    unit.status_id, unit.sale_id = in_stock, None  # trigger puts it back in stock_quantity
                    pieces.append(_piece_label(unit))
            elif physical_unit_service.is_tracked(db, sale.variant_id):
                raise HTTPException(
                    status_code=422,
                    detail=f"{name} is now tracked by HUID but this bill has no piece recorded. "
                    "Add the returned piece in Inventory (HUID & pieces), then record the return.",
                )
            else:
                variant = db.query(ProductVariant).filter(ProductVariant.id == sale.variant_id).with_for_update().one()
                variant.stock_quantity = (variant.stock_quantity or 0) + line.quantity

            # The last unit back takes whatever is left, so rounding never leaves paise behind.
            if line.quantity == left:
                value = money(sale.final_price) - money(sale.returned_amount)
            else:
                value = money(Decimal(sale.final_price) * line.quantity / sale.quantity)
            sale.returned_quantity += line.quantity
            sale.returned_amount = money(sale.returned_amount) + value
            returned_lines.append((sale, line.quantity, value, pieces))

        taxable = sum((value for _, _, value, _ in returned_lines), Decimal(0))
        cgst, sgst = split_gst(taxable) if order.tax_amount else (Decimal(0), Decimal(0))
        deduction = money(payload.deduction_amount)
        if deduction > 0 and not payload.deduction_reason:
            raise HTTPException(status_code=422, detail="Write the reason for the deduction.")
        if deduction > taxable + cgst + sgst:
            raise HTTPException(status_code=422, detail="The deduction can't be more than the value being returned.")
        refund = taxable + cgst + sgst - deduction

        customer = bill_customer
        if payload.customer_id is not None:
            customer = db.query(User).filter(User.id == payload.customer_id).first()
            if customer is None:
                raise HTTPException(status_code=404, detail="Selected customer was not found")
        if payload.refund_method == "store_credit":
            SalesService.require_named_customer(customer, "Refund to store credit")

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        sale_return = SaleReturn(
            store_id=store_id,
            order_id=order.id,
            credit_note_number=_next_credit_note_number(db, store_id, now),
            customer_id=customer.id if customer else None,
            reason=payload.reason,
            reason_note=payload.reason_note or None,
            taxable_value=taxable,
            cgst=cgst,
            sgst=sgst,
            deduction_amount=deduction,
            deduction_reason=payload.deduction_reason if deduction > 0 else None,
            refund_amount=refund,
            refund_method=payload.refund_method,
            refund_reference=payload.refund_reference or None,
            created_by_admin_id=admin_id,
            created_at=now,
            lines=[
                SaleReturnLine(sale_id=sale.id, quantity=qty, taxable_value=value, pieces=pieces)
                for sale, qty, value, pieces in returned_lines
            ],
        )
        db.add(sale_return)
        db.flush()

        if payload.refund_method == "store_credit" and refund > 0:
            db.add(
                StoreCreditEntry(
                    customer_id=customer.id, store_id=store_id, amount=refund, sale_return_id=sale_return.id,
                    note=f"Return, credit note {sale_return.credit_note_number}", created_by_admin_id=admin_id,
                )
            )

        cancelled = []
        for sale, *_ in returned_lines:
            for custom_order in _open_alterations(db, sale, order):
                AdminCustomOrderService.set_status(
                    db, store_id=store_id, order_id=custom_order.id, admin_id=admin_id,
                    payload=CustomOrderStatusUpdateRequest(
                        status_code="cancelled", note=f"Item returned, credit note {sale_return.credit_note_number}"
                    ),
                )
                cancelled.append(custom_order.id)
        db.flush()

    return {
        "id": sale_return.id,
        "credit_note_number": sale_return.credit_note_number,
        "taxable_value": float(taxable),
        "cgst": float(cgst),
        "sgst": float(sgst),
        "deduction_amount": float(deduction),
        "refund_amount": float(refund),
        "refund_method": payload.refund_method,
        "refund_reference": sale_return.refund_reference,
        "customer_name": customer.full_name if customer else None,
        "cancelled_custom_order_ids": cancelled,
    }


def build_credit_note_pdf(db: Session, store_id: UUID, return_id: int) -> tuple[str, bytes]:
    sale_return = (
        db.query(SaleReturn).filter(SaleReturn.id == return_id, SaleReturn.store_id == store_id).first()
    )
    if sale_return is None:
        raise HTTPException(status_code=404, detail="Credit note not found")

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 40

    def row(label: str, amount: str | None = None, *, x: int = 40, font: str = "Helvetica", size: int = 11, gap: int = 0) -> None:
        nonlocal y
        y -= gap
        if y < 60:
            pdf.showPage()
            y = height - 40
        pdf.setFont(font, size)
        pdf.drawString(x, y, label)
        if amount is not None:
            pdf.drawRightString(width - 40, y, amount)
        y -= size + 5

    customer = sale_return.customer
    row("Urjaa Ornaments", font="Helvetica-Bold", size=16)
    row("CREDIT NOTE", font="Helvetica-Bold", size=13)
    row(f"Credit Note Number: {sale_return.credit_note_number}")
    row(f"Date: {ist_text(sale_return.created_at)}")
    row(f"Against bill: {sale_return.order.invoice_number or '-'}")
    row("Customer", font="Helvetica-Bold", size=12, gap=10)
    row(f"Name: {customer.full_name if customer else 'Walk-in Customer'}")
    row(f"Phone: {(customer.phone if customer else '') or '-'}")
    reason = REASON_LABELS.get(sale_return.reason, sale_return.reason)
    row(f"Reason: {reason}" + (f" - {sale_return.reason_note}" if sale_return.reason_note else ""))

    row("Returned Items", font="Helvetica-Bold", size=12, gap=10)
    for line in sale_return.lines:
        product_name = line.sale.product.name if line.sale and line.sale.product else "Unknown Product"
        row(f"{product_name} x{line.quantity}   HSN {HSN_JEWELLERY}", f"INR {line.taxable_value:,.2f}")
        if line.pieces:
            row(f"Pieces: {', '.join(line.pieces)}", x=56, size=10)

    row("Taxable value", f"INR {sale_return.taxable_value:,.2f}", gap=8)
    row("CGST 1.5% reversed", f"INR {sale_return.cgst:,.2f}")
    row("SGST 1.5% reversed", f"INR {sale_return.sgst:,.2f}")
    if sale_return.deduction_amount:
        row(f"Less: deduction ({sale_return.deduction_reason})", f"- INR {sale_return.deduction_amount:,.2f}")
    row("Refund amount", f"INR {sale_return.refund_amount:,.2f}", font="Helvetica-Bold", size=12, gap=4)
    method = METHOD_LABELS.get(sale_return.refund_method, sale_return.refund_method)
    row(f"Refunded by: {method}" + (f" (Ref {sale_return.refund_reference})" if sale_return.refund_reference else ""))

    pdf.showPage()
    pdf.save()
    return f"credit_note_{sale_return.credit_note_number}.pdf", buffer.getvalue()
