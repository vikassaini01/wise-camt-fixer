#!/usr/bin/env python3
"""
Fix Wise camt.053.001.10 XML statement files to be more compatible with strict
importers (e.g., SimpleBooks), by "downgrading" to camt.053.001.02 and normalizing
a few structures.

Usage:
  python fix_wise_camt053.py input.xml output.xml
  python fix_wise_camt053.py input.xml  # writes input_FIXED.xml

Notes:
- This is intentionally conservative: it does not attempt to rebuild full TxDtls
  from Wise-specific data, only moves AddtlNtryInf into RmtInf/Ustrd.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

CAMT_10 = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.10"
CAMT_02 = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"

def localname(tag: str) -> str:
    """Return local name of an XML tag (strip namespace)."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag

def qname(ns: str, name: str) -> str:
    return f"{{{ns}}}{name}"

def indent(elem: ET.Element, level: int = 0) -> None:
    """In-place pretty indentation for ElementTree."""
    i = "\n" + level * "  "
    if len(elem):
        if not (elem.text or "").strip():
            elem.text = i + "  "
        for child in elem:
            indent(child, level + 1)
        if not (elem.tail or "").strip():
            elem.tail = i
    else:
        if level and not (elem.tail or "").strip():
            elem.tail = i

def replace_namespace(root: ET.Element, old_ns: str, new_ns: str) -> None:
    """
    Rewrite all tags/attributes that use old_ns to new_ns.
    This effectively "downgrades" the document to camt.053.001.02 namespace.
    """
    for elem in root.iter():
        if elem.tag.startswith("{"):
            ns, ln = elem.tag[1:].split("}", 1)
            if ns == old_ns:
                elem.tag = qname(new_ns, ln)

        # Attributes can also be namespaced; rarely used here, but we handle it.
        new_attrib = {}
        changed = False
        for k, v in elem.attrib.items():
            if k.startswith("{"):
                ns, ln = k[1:].split("}", 1)
                if ns == old_ns:
                    new_attrib[qname(new_ns, ln)] = v
                    changed = True
                else:
                    new_attrib[k] = v
            else:
                new_attrib[k] = v
        if changed:
            elem.attrib.clear()
            elem.attrib.update(new_attrib)

def findall_ns(elem: ET.Element, ns: str, path: str) -> list[ET.Element]:
    """
    Findall with a simple ns mapping. Path should use bare tag names separated by /.
    """
    parts = path.split("/")
    xpath = "."
    for p in parts:
        xpath += f"/{qname(ns, p)}"
    return elem.findall(xpath)

def findone_ns(elem: ET.Element, ns: str, path: str) -> ET.Element | None:
    lst = findall_ns(elem, ns, path)
    return lst[0] if lst else None

def ensure_child(parent: ET.Element, ns: str, tag: str) -> ET.Element:
    child = parent.find(qname(ns, tag))
    if child is None:
        child = ET.SubElement(parent, qname(ns, tag))
    return child

def normalize_status(ntry: ET.Element, ns: str) -> None:
    """
    Wise sometimes uses:
      <Sts><Cd>BOOK</Cd></Sts>
    Some importers expect:
      <Sts>BOOK</Sts>
    """
    sts = ntry.find(qname(ns, "Sts"))
    if sts is None:
        return

    # if it has a single child Cd and no direct text -> flatten
    cd = sts.find(qname(ns, "Cd"))
    if cd is not None and (sts.text or "").strip() == "":
        val = (cd.text or "").strip()
        # Remove all children under <Sts>
        for child in list(sts):
            sts.remove(child)
        sts.text = val if val else "BOOK"

def remove_total_entries(stmt: ET.Element, ns: str) -> None:
    """
    Remove <TtlNtries> blocks (some strict validators/importers reject them).
    """
    for ttl in list(stmt.findall(f".//{qname(ns,'TtlNtries')}")):
        parent = _find_parent(stmt, ttl)
        if parent is not None:
            parent.remove(ttl)

def _find_parent(root: ET.Element, target: ET.Element) -> ET.Element | None:
    for p in root.iter():
        for c in list(p):
            if c is target:
                return p
    return None

def normalize_dates(root: ET.Element, ns: str) -> None:
    """
    Convert <BookgDt><DtTm>...</DtTm></BookgDt> to <BookgDt><Dt>YYYY-MM-DD</Dt></BookgDt>
    Same for <ValDt>.
    """
    for dt_container_tag in ("BookgDt", "ValDt"):
        for container in root.findall(f".//{qname(ns, dt_container_tag)}"):
            dt = container.find(qname(ns, "Dt"))
            dttm = container.find(qname(ns, "DtTm"))
            if dt is None and dttm is not None and (dttm.text or "").strip():
                # extract date part
                t = dttm.text.strip()
                date_part = t.split("T", 1)[0]
                # remove DtTm, add Dt
                container.remove(dttm)
                dt = ET.SubElement(container, qname(ns, "Dt"))
                dt.text = date_part

def ensure_acct_svcr_ref(ntry: ET.Element, ns: str) -> None:
    """
    Ensure <AcctSvcrRef> exists. If missing, attempt to derive from NtryRef / AddtlNtryInf.
    """
    acct_ref = ntry.find(qname(ns, "AcctSvcrRef"))
    if acct_ref is not None and (acct_ref.text or "").strip():
        return

    # candidate sources
    ntry_ref = ntry.find(qname(ns, "NtryRef"))
    addtl = ntry.find(qname(ns, "AddtlNtryInf"))

    value = None
    if ntry_ref is not None and (ntry_ref.text or "").strip():
        value = ntry_ref.text.strip()
    elif addtl is not None and (addtl.text or "").strip():
        # crude hash-like fallback from additional info
        s = re.sub(r"\s+", " ", addtl.text.strip())
        value = f"ADDINFO:{s[:60]}"

    if value:
        # Insert near NtryRef if possible, else append.
        acct_ref = ET.Element(qname(ns, "AcctSvcrRef"))
        acct_ref.text = value
        # place after NtryRef if present
        if ntry_ref is not None:
            parent = ntry
            idx = list(parent).index(ntry_ref)
            parent.insert(idx + 1, acct_ref)
        else:
            ntry.append(acct_ref)

def move_addtl_info_into_tx(ntry: ET.Element, ns: str) -> None:
    """
    Take <AddtlNtryInf> and ensure it is present as a transaction remittance:
      NtryDtls/TxDtls/RmtInf/Ustrd
    If NtryDtls/TxDtls doesn't exist, create minimal skeleton.
    """
    addtl = ntry.find(qname(ns, "AddtlNtryInf"))
    if addtl is None or not (addtl.text or "").strip():
        return

    text = addtl.text.strip()

    ntry_dtls = ensure_child(ntry, ns, "NtryDtls")

    # Prefer: NtryDtls/TxDtls (can be multiple)
    tx_dtls_list = ntry_dtls.findall(qname(ns, "TxDtls"))
    if not tx_dtls_list:
        tx = ET.SubElement(ntry_dtls, qname(ns, "TxDtls"))
        tx_dtls_list = [tx]

    for tx in tx_dtls_list:
        rmt = tx.find(qname(ns, "RmtInf"))
        if rmt is None:
            rmt = ET.SubElement(tx, qname(ns, "RmtInf"))
        # append Ustrd (unstructured remittance)
        ustrd = ET.SubElement(rmt, qname(ns, "Ustrd"))
        ustrd.text = text

    # Keep AddtlNtryInf or remove? Some importers dislike it; SimpleBooks often doesn't need it.
    # We'll remove it to reduce surprises.
    ntry.remove(addtl)

def detect_namespace(root: ET.Element) -> str | None:
    if root.tag.startswith("{"):
        return root.tag[1:].split("}", 1)[0]
    return None

def fix_wise_statement(input_path: Path, output_path: Path) -> None:
    tree = ET.parse(str(input_path))
    root = tree.getroot()

    ns = detect_namespace(root)
    if ns is None:
        raise ValueError("Input XML has no namespace; expected ISO 20022 camt.053.")

    # If it's already camt.053.001.02, we still normalize the problematic structures.
    # If it's Wise camt.053.001.10, downgrade to 001.02.
    if ns == CAMT_10:
        replace_namespace(root, CAMT_10, CAMT_02)
        ns = CAMT_02

    # Basic sanity: must contain BkToCstmrStmt
    if root.find(f".//{qname(ns,'BkToCstmrStmt')}") is None:
        raise ValueError("Could not find BkToCstmrStmt; not a camt.053 statement?")

    # Apply fixes per statement
    for stmt in root.findall(f".//{qname(ns,'Stmt')}"):
        remove_total_entries(stmt, ns)

        # For each entry
        for ntry in stmt.findall(f".//{qname(ns,'Ntry')}"):
            normalize_status(ntry, ns)
            ensure_acct_svcr_ref(ntry, ns)
            move_addtl_info_into_tx(ntry, ns)

    normalize_dates(root, ns)

    # Pretty output
    indent(root)

    # Ensure the output uses the correct default namespace
    ET.register_namespace("", ns)

    tree.write(str(output_path), encoding="utf-8", xml_declaration=True)

def main() -> int:
    parser = argparse.ArgumentParser(description="Fix Wise camt.053 statements for strict importers.")
    parser.add_argument("input", type=Path, help="Input Wise XML file")
    parser.add_argument("output", type=Path, nargs="?", default=None, help="Output fixed XML file")
    args = parser.parse_args()

    in_path: Path = args.input
    if not in_path.exists():
        print(f"ERROR: Input file not found: {in_path}", file=sys.stderr)
        return 2

    out_path: Path
    if args.output is None:
        out_path = in_path.with_name(in_path.stem + "_FIXED" + in_path.suffix)
    else:
        out_path = args.output

    try:
        fix_wise_statement(in_path, out_path)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"Fixed file written to: {out_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
