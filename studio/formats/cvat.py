"""CVAT "CVAT for images 1.1" XML (pure conversion): boxes and polygons.

``build`` writes one ``annotations.xml``; ``parse`` reads one. Structure from the public CVAT
page (``docs/FORMATS.md`` section 4): ``<annotations><version/><meta/><image id name width
height>`` holding ``<box label xtl ytl xbr ybr occluded z_order>`` and ``<polygon label points
occluded z_order>`` with ``points`` = ``x,y;x,y;...``. Keypoint sets are NOT written (CVAT needs
a skeleton definition we have not verified); every shape we cannot read is listed in ``skipped``
by type, never dropped silently.
"""

import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from typing import Any

SUPPORTED = ("box", "polygon")


class CvatError(ValueError):
    """The XML cannot be read as CVAT for images 1.1."""


def _r(value: float) -> str:
    return f"{float(value):.2f}"


def build(
    images: Sequence[Mapping[str, Any]], classes: Sequence[Mapping[str, Any]], name: str = "export"
) -> tuple[str, int]:
    """Return ``(xml_text, skipped)``; ``skipped`` counts annotations of kinds CVAT export omits."""
    root = ET.Element("annotations")
    ET.SubElement(root, "version").text = "1.1"
    task = ET.SubElement(ET.SubElement(root, "meta"), "task")
    ET.SubElement(task, "name").text = name
    ET.SubElement(task, "size").text = str(len(images))
    ET.SubElement(task, "mode").text = "annotation"
    labels = ET.SubElement(task, "labels")
    names = {}
    for cls in classes:
        names[cls["id"]] = cls["name"]
        label = ET.SubElement(labels, "label")
        ET.SubElement(label, "name").text = cls["name"]
        ET.SubElement(label, "color").text = cls.get("color") or "#888888"
        ET.SubElement(label, "type").text = "any"
    skipped = 0
    for number, image in enumerate(images):
        node = ET.SubElement(
            root,
            "image",
            id=str(number),
            name=image["file_name"],
            width=str(image["width"]),
            height=str(image["height"]),
        )
        for item in image["annotations"]:
            kind, data = item["kind"], item["data"]
            label = names[item["class_id"]]
            if kind == "box":
                ET.SubElement(
                    node,
                    "box",
                    label=label,
                    occluded="0",
                    xtl=_r(data["x"]),
                    ytl=_r(data["y"]),
                    xbr=_r(data["x"] + data["w"]),
                    ybr=_r(data["y"] + data["h"]),
                    z_order="0",
                )
            elif kind == "polygon":
                points = ";".join(f"{_r(x)},{_r(y)}" for x, y in data["points"])
                ET.SubElement(
                    node, "polygon", label=label, occluded="0", points=points, z_order="0"
                )
            else:
                skipped += 1
    ET.indent(root)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
        root, encoding="unicode"
    ), skipped


def parse(xml_text: str | bytes) -> dict[str, Any]:
    """Read CVAT for images 1.1.

    Returns ``{"images": [{"file_name", "width", "height", "annotations": [{"label", "kind",
    "data"}]}], "skipped": [str, ...]}``.
    """
    raw = xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise CvatError("This XML declares entities or a DOCTYPE, which is refused for safety.")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise CvatError(f"This is not valid XML: {error}") from error
    if root.tag != "annotations":
        raise CvatError("This does not look like CVAT for images: the root is not <annotations>.")
    images = []
    skipped: list[str] = []
    counts: dict[str, int] = {}
    for node in root.iter("image"):
        name = node.get("name")
        if not name:
            skipped.append("an <image> without a name was ignored")
            continue
        record: dict[str, Any] = {
            "file_name": name,
            "width": _int(node.get("width")),
            "height": _int(node.get("height")),
            "annotations": [],
        }
        images.append(record)
        for shape in node:
            tag = shape.tag
            label = shape.get("label")
            try:
                if tag == "box" and label:
                    if _float(shape.get("rotation")):
                        raise ValueError("rotated boxes are not supported")
                    x0, y0 = float(shape.get("xtl")), float(shape.get("ytl"))
                    x1, y1 = float(shape.get("xbr")), float(shape.get("ybr"))
                    data = {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
                    record["annotations"].append({"label": label, "kind": "box", "data": data})
                elif tag == "polygon" and label:
                    points = [
                        [float(v) for v in pair.split(",")]
                        for pair in shape.get("points", "").split(";")
                        if pair.strip()
                    ]
                    if len(points) < 3 or any(len(p) != 2 for p in points):
                        raise ValueError("a polygon needs at least 3 x,y points")
                    record["annotations"].append(
                        {"label": label, "kind": "polygon", "data": {"points": points}}
                    )
                else:
                    counts[tag] = counts.get(tag, 0) + 1
            except (TypeError, ValueError) as error:
                skipped.append(f"{name}: <{tag}> {error}")
    skipped += [
        f"{n} <{tag}> shape(s) are not supported yet and were skipped" for tag, n in counts.items()
    ]
    return {"images": images, "skipped": skipped}


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _float(value: str | None) -> float:
    try:
        return float(value) if value is not None else 0.0
    except ValueError:
        return 0.0
