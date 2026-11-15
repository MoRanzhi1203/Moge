##############################
# core/resources/jsonc.py - 允许注释与尾逗号的 JSON 解析
##############################

import json
import re


def loads_jsonc(text: str):
    """ 去除 // 与 /* */ 注释及尾逗号，不破坏字符串内容 """
    output = []
    index = 0
    length = len(text)
    in_string = False
    escaped = False
    while index < length:
        char = text[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < length:
            nxt = text[index + 1]
            if nxt == "/":
                index += 2
                while index < length and text[index] not in "\r\n":
                    index += 1
                continue
            if nxt == "*":
                index += 2
                while index + 1 < length and not (text[index] == "*" and text[index + 1] == "/"):
                    index += 1
                index += 2
                continue
        output.append(char)
        index += 1

    cleaned = re.sub(r",\s*([}\]])", r"\1", "".join(output))
    return json.loads(cleaned)
