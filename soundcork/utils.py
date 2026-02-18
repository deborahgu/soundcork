import xml.etree.ElementTree as ET
from typing import Optional


def strip_element_text(elem: Optional[ET.Element]) -> str:
    if elem == None:
        return ""
    else:
        text = elem.text
        if not text:
            return ""
        else:
            return text.strip()
