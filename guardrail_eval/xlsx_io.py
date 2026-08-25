"""Dependency-free .xlsx read/write on the Python standard library.

`openpyxl` was not available in the target environment, so both directions are
implemented directly against the Office Open XML package format using only
`zipfile` and `xml.etree.ElementTree`.

Reading handles the two ways spreadsheet cells store text (the shared-string
table and inline strings) plus relationship-map sheet resolution, so sheets are
addressable by name rather than by file index. Writing emits inline strings with
`xml:space="preserve"` so the long multi-line clinical free text in a results
export survives a round trip unaltered.
"""
import csv
import zipfile
import xml.etree.ElementTree as ET

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
DOCREL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKGREL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


# --------------------------------------------------------------------- read
def _shared_strings(z):
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(t.text or "" for t in si.iter(MAIN + "t"))
            for si in root.iter(MAIN + "si")]


def _sheet_paths(z):
    """Map sheet display name -> part path, via the workbook relationship map."""
    workbook = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels.iter(PKGREL + "Relationship")}
    out = {}
    for sheet in workbook.iter(MAIN + "sheet"):
        path = target[sheet.get(DOCREL + "id")].lstrip("/")
        out[sheet.get("name")] = path if path.startswith("xl/") else "xl/" + path
    return out


def _column_index(cell_ref):
    """'AB12' -> 27 (zero-based column index)."""
    n = 0
    for ch in "".join(c for c in cell_ref if c.isalpha()):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def sheet_names(path):
    with zipfile.ZipFile(path) as z:
        return list(_sheet_paths(z).keys())


def read_sheet(path, name):
    """Read one sheet into a list of dicts keyed by the header row."""
    with zipfile.ZipFile(path) as z:
        shared = _shared_strings(z)
        paths = _sheet_paths(z)
        if name not in paths:
            raise KeyError("sheet %r not in %s" % (name, list(paths)))
        root = ET.fromstring(z.read(paths[name]))
        rows = []
        for row in root.iter(MAIN + "row"):
            cells = {}
            for c in row.iter(MAIN + "c"):
                kind = c.get("t")
                if kind == "inlineStr":
                    inline = c.find(MAIN + "is")
                    value = "".join(t.text or "" for t in inline.iter(MAIN + "t")) if inline is not None else ""
                else:
                    v = c.find(MAIN + "v")
                    if v is None or v.text is None:
                        continue
                    value = shared[int(v.text)] if kind == "s" else v.text
                if value != "":
                    cells[_column_index(c.get("r"))] = value
            if cells:
                rows.append(cells)
    if not rows:
        return []
    width = max(max(r) for r in rows) + 1
    headers = [rows[0].get(i, "col%d" % i) for i in range(width)]
    return [{headers[i]: r.get(i, "") for i in range(width)} for r in rows[1:]]


def column_by_prefix(row, prefix):
    """Fetch a value whose header starts with `prefix`.

    The source workbooks carry annotated headers such as
    'gold_checklist_id (Arm C source)', so exact-key lookup is brittle.
    """
    want = prefix.replace(" ", "").lower()
    for key in row:
        if key.replace(" ", "").lower().startswith(want):
            return row[key]
    raise KeyError(prefix)


# -------------------------------------------------------------------- write
def _escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def _col_letters(idx):
    letters, idx = "", idx + 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def csv_to_xlsx(csv_path, xlsx_path, sheet_name="results"):
    """Convert a results CSV to a single-sheet .xlsx, preserving newlines."""
    with open(csv_path, newline="") as f:
        rows = list(csv.reader(f))

    body = "".join(
        '<row r="%d">%s</row>' % (
            r_i + 1,
            "".join('<c r="%s%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
                    % (_col_letters(c_i), r_i + 1, _escape(val))
                    for c_i, val in enumerate(row)))
        for r_i, row in enumerate(rows))

    parts = {
        "[Content_Types].xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>',
        "_rels/.rels":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>',
        "xl/workbook.xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets></workbook>' % sheet_name,
        "xl/_rels/workbook.xml.rels":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>',
        "xl/worksheets/sheet1.xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData>%s</sheetData></worksheet>' % body,
    }
    with zipfile.ZipFile(xlsx_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in parts.items():
            z.writestr(name, content)
    return xlsx_path, len(rows)


def write_workbook(path, sheets):
    """Write a multi-sheet .xlsx. `sheets` maps sheet name -> list of row lists."""
    ct, rels, sheet_tags, sheet_rels, parts = [], [], [], [], {}
    for i, (name, rows) in enumerate(sheets.items(), start=1):
        part = "xl/worksheets/sheet%d.xml" % i
        ct.append('<Override PartName="/%s" ContentType="application/vnd.openxmlformats-'
                  'officedocument.spreadsheetml.worksheet+xml"/>' % part)
        sheet_tags.append('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (name, i, i))
        sheet_rels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/'
                          'officeDocument/2006/relationships/worksheet" '
                          'Target="worksheets/sheet%d.xml"/>' % (i, i))
        body = "".join(
            '<row r="%d">%s</row>' % (
                r_i + 1,
                "".join('<c r="%s%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
                        % (_col_letters(c_i), r_i + 1, _escape(str(v)))
                        for c_i, v in enumerate(row)))
            for r_i, row in enumerate(rows))
        parts[part] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                       '<sheetData>%s</sheetData></worksheet>' % body)

    parts["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.spreadsheetml.sheet.main+xml"/>' + "".join(ct) + '</Types>')
    parts["_rels/.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    parts["xl/workbook.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets>' + "".join(sheet_tags) + '</sheets></workbook>')
    parts["xl/_rels/workbook.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(sheet_rels) + '</Relationships>')

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in parts.items():
            z.writestr(name, content)
    return path
