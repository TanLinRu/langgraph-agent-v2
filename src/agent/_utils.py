import re

_FILE_PATH_RE = re.compile(r'(?:src|docs|tests|ui|memory|config|skills)[/\\][\w./\\-]+\.\w+')
_CODE_FILE_RE = re.compile(r'[\w-]+\.(?:py|ts|js|vue|html|json|md|toml|yaml)')

def extract_file_refs(text: str) -> list[str]:
    refs = set(_FILE_PATH_RE.findall(text))
    refs.update(_CODE_FILE_RE.findall(text))
    return sorted(refs)

def is_punctuation_only(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return all(c in ".,!?;:。！？；：、 \n\t...·" for c in stripped)

SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}
