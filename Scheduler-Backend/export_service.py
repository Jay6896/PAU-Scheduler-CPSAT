# export_service.py  — scheduler-style Excel + PDF
"""
Export service for generating Excel and PDF timetable files
(scheduler.py style: Course Key + Timetable with Day/Time/Course/Room/Lecturer)
"""

import io
import re
from typing import List, Dict, Any
from datetime import datetime

# Excel writer (scheduler style)
import xlsxwriter

# Optional PDF deps
try:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False


class TimetableExportService:
    """Service for exporting timetables in scheduler.py format"""

    def __init__(self):
        self.days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    # ---------- helpers ----------
    def _sanitize_sheet_name(self, name: str, used: set) -> str:
        sanitized = re.sub(r'[^a-zA-Z0-9\s]', '_', name or "Group")
        sanitized = re.sub(r'_+', '_', sanitized).strip('_')[:31] or "Group"
        base = sanitized
        n = 0
        while sanitized.lower() in used:
            n += 1
            suffix = f"_{n}"
            sanitized = f"{base[:31-len(suffix)]}{suffix}"
        used.add(sanitized.lower())
        return sanitized

    def _grid_to_rows(self, timetable_grid: List[List[str]]) -> List[Dict[str, str]]:
        """Convert grid (Time, Mon..Fri cells) to rows: Day/Time/Course/Room/Lecturer."""
        rows = []
        for r in timetable_grid:
            if not r:
                continue
            time_slot = r[0]
            for day_idx, cell in enumerate(r[1:]):
                if not cell:
                    continue
                text = str(cell).strip()
                if not text or "BREAK" in text.upper():
                    continue
                # Expected: "Course: ABC123, Lecturer: Dr X, Room: LH-1"
                course = lecturer = room = ""
                parts = [p.strip() for p in text.split(',')]
                for p in parts:
                    if p.lower().startswith("course:"):
                        course = p.split(":", 1)[1].strip()
                    elif p.lower().startswith("lecturer:"):
                        lecturer = p.split(":", 1)[1].strip()
                    elif p.lower().startswith("room:"):
                        room = p.split(":", 1)[1].strip()
                rows.append({
                    "Day": self.days_of_week[day_idx] if day_idx < len(self.days_of_week) else f"Day{day_idx+1}",
                    "Time": time_slot,
                    "Course": course or "Unknown",
                    "Room": room or "Unknown",
                    "Lecturer": lecturer or "TBD",
                })
        # Sort by Day index, then by Time (string-safe)
        day_index = {d: i for i, d in enumerate(self.days_of_week)}
        rows.sort(key=lambda x: (day_index.get(x["Day"], 99), x["Time"]))
        return rows

    def _course_key_from_rows(self, rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Build Course Key as in scheduler.py (Course Code + Name). Name unknown -> empty."""
        seen = {}
        for r in rows:
            code = r["Course"]
            if code and code not in seen:
                seen[code] = {"Course Code": code, "Course Name": ""}  # name unknown from grid
        return list(seen.values())

    # ---------- Excel (scheduler-style) ----------
    def export_to_excel(self, timetable_data: List[Dict[str, Any]], filename: str = None) -> io.BytesIO:
        """
        Export to Excel using the same output format as scheduler.py.
        timetable_data must be a list of dicts with keys: 'student_group', 'timetable'
        where 'timetable' is a grid (rows) and first column is 'Time'.
        """
        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {'in_memory': True})

        header_format = workbook.add_format({"bold": True, "bg_color": "#D3D3D3", "border": 1})
        cell_format = workbook.add_format({"border": 1})

        used_sheet_names = set()

        for item in timetable_data:
            student_group = item.get("student_group")
            grid = item.get("timetable", [])

            group_name = getattr(student_group, "name", None) or f"Group_{getattr(student_group, 'id', '')}"
            sheet_name = self._sanitize_sheet_name(group_name, used_sheet_names)
            ws = workbook.add_worksheet(sheet_name)

            # Transform grid to scheduler-style rows
            rows = self._grid_to_rows(grid)
            key = self._course_key_from_rows(rows)

            # --- Course Key header
            ws.write(0, 0, "Course Key", header_format)
            ws.write(1, 0, "Course Code", header_format)
            ws.write(1, 1, "Course Name", header_format)
            r = 2
            for k in key:
                ws.write(r, 0, k["Course Code"], cell_format)
                ws.write(r, 1, k["Course Name"], cell_format)
                r += 1

            # --- Timetable header
            start_row = r + 2
            ws.write(start_row - 1, 0, "Timetable", header_format)
            headers = ["Day", "Time", "Course", "Room", "Lecturer"]
            for c, h in enumerate(headers):
                ws.write(start_row, c, h, header_format)

            # --- Timetable rows
            rr = start_row + 1
            for row in rows:
                ws.write(rr, 0, row["Day"], cell_format)
                ws.write(rr, 1, row["Time"], cell_format)
                ws.write(rr, 2, row["Course"], cell_format)
                ws.write(rr, 3, row["Room"], cell_format)
                ws.write(rr, 4, row["Lecturer"], cell_format)
                rr += 1

            # simple column widths
            ws.set_column(0, 0, 10)  # Day
            ws.set_column(1, 1, 12)  # Time
            ws.set_column(2, 2, 18)  # Course
            ws.set_column(3, 3, 18)  # Room
            ws.set_column(4, 4, 22)  # Lecturer

        workbook.close()
        buffer.seek(0)
        return buffer

    # ---------- PDF ----------
    def export_to_pdf(self, timetable_data: List[Dict[str, Any]], filename: str = None) -> io.BytesIO:
        """
        Export to PDF with the same logical rows as the scheduler view.
        """
        if not REPORTLAB_AVAILABLE:
            raise ImportError("ReportLab is required for PDF export. Install with: pip install reportlab")

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            rightMargin=0.5*inch,
            leftMargin=0.5*inch,
            topMargin=0.75*inch,
            bottomMargin=0.5*inch
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('T', parent=styles['Heading1'], alignment=TA_CENTER, fontSize=20, spaceAfter=12)

        story = []
        story.append(Paragraph("University Timetable", title_style))
        story.append(Paragraph(datetime.now().strftime("%B %d, %Y %H:%M"), styles['Normal']))
        story.append(Spacer(1, 14))

        # quick summary
        total_groups = len(timetable_data)
        total_classes = 0
        for item in timetable_data:
            rows = self._grid_to_rows(item.get("timetable", []))
            total_classes += len(rows)

        summary_tbl = Table([
            ["Total Student Groups", str(total_groups)],
            ["Total Classes Scheduled", str(total_classes)],
        ])
        summary_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ]))
        story.append(summary_tbl)
        story.append(PageBreak())

        # per group
        for item in timetable_data:
            student_group = item.get("student_group")
            group_name = getattr(student_group, "name", None) or f"Group_{getattr(student_group, 'id', '')}"
            rows = self._grid_to_rows(item.get("timetable", []))

            story.append(Paragraph(f"Timetable for {group_name}", styles['Heading2']))
            story.append(Spacer(1, 6))

            table_data = [["Day", "Time", "Course", "Room", "Lecturer"]] + [
                [r["Day"], r["Time"], r["Course"], r["Room"], r["Lecturer"]] for r in rows
            ]

            t = Table(table_data)
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
            ]))
            story.append(t)
            story.append(PageBreak())

        doc.build(story)
        buffer.seek(0)
        return buffer


def create_export_service() -> TimetableExportService:
    return TimetableExportService()
