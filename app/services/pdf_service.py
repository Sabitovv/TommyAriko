from datetime import datetime
from pathlib import Path
import logging
import calendar

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.config import get_settings
from app.models.entities import Application

logger = logging.getLogger(__name__)


class PDFService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.output_dir = self._resolve_output_dir(self.settings.pdf_output_dir)

    @staticmethod
    def _resolve_output_dir(configured_path: str) -> Path:
        primary = Path(configured_path)
        try:
            primary.mkdir(parents=True, exist_ok=True)
            return primary
        except PermissionError:
            fallback = Path("storage/pdfs")
            fallback.mkdir(parents=True, exist_ok=True)
            logger.warning(
                "pdf_output_fallback",
                extra={"configured_path": configured_path, "fallback": str(fallback)},
            )
            return fallback

    def build_warranty_pdf(self, app: Application) -> str:
        file_path = self.output_dir / f"{app.number}.pdf"
        qr_path = self.output_dir / f"{app.number}_qr.png"
        qrcode.make(f"warranty:{app.number}").save(qr_path)

        c = canvas.Canvas(str(file_path), pagesize=A4)
        width, height = A4

        c.setFillColor(colors.HexColor("#F4F7FB"))
        c.rect(0, 0, width, height, stroke=0, fill=1)

        c.setFillColor(colors.HexColor("#123B5D"))
        c.roundRect(36, height - 140, width - 72, 92, 12, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 22)
        c.drawString(56, height - 88, "Гарантийный талон")
        c.setFont("Helvetica", 11)
        c.drawString(56, height - 108, "Wildberries Warranty Activation")
        c.drawString(width - 190, height - 108, "[LOGO PLACEHOLDER]")

        c.setFillColor(colors.HexColor("#1C6EA4"))
        c.roundRect(36, height - 180, width - 72, 28, 8, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, height - 171, f"Номер гарантии: {app.number}")

        activation_dt = datetime.now().replace(microsecond=0)
        end_dt = self._add_months(activation_dt, app.product.warranty_months)

        rows = [
            ("ФИО", app.customer_full_name),
            ("Город", app.city),
            ("Телефон", app.phone),
            ("Товар", app.product.name),
            ("Артикул", app.article),
            ("Дата активации", activation_dt.strftime("%Y-%m-%d")),
            ("Срок гарантии", f"{app.product.warranty_months} мес."),
            ("Дата окончания гарантии", end_dt.strftime("%Y-%m-%d")),
        ]

        y = height - 225
        c.setFillColor(colors.HexColor("#0F172A"))
        for label, value in rows:
            c.setFillColor(colors.HexColor("#334155"))
            c.setFont("Helvetica-Bold", 11)
            c.drawString(50, y, f"{label}:")
            c.setFillColor(colors.HexColor("#0F172A"))
            c.setFont("Helvetica", 11)
            c.drawString(205, y, str(value))
            y -= 26

        c.setFillColor(colors.HexColor("#E7EFF7"))
        c.roundRect(36, 82, width - 72, 95, 10, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#0F172A"))
        c.setFont("Helvetica", 10)
        c.drawString(50, 152, "Проверка подлинности:")
        c.setFont("Helvetica", 9)
        c.drawString(50, 136, "Отсканируйте QR-код для сверки номера гарантийного талона.")
        c.drawImage(str(qr_path), width - 170, 92, width=100, height=100)

        c.setFillColor(colors.HexColor("#475569"))
        c.setFont("Helvetica", 9)
        c.drawString(50, 62, "Документ сформирован автоматически сервисом активации гарантии.")

        c.showPage()
        c.save()
        return str(file_path)

    @staticmethod
    def _add_months(dt: datetime, months: int) -> datetime:
        month = dt.month - 1 + months
        year = dt.year + month // 12
        month = month % 12 + 1
        day = min(dt.day, calendar.monthrange(year, month)[1])
        return dt.replace(year=year, month=month, day=day)
