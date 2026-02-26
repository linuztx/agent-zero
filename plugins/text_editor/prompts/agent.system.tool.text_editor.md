### text_editor
native file read write patch with line numbers
prefer no code_execution_tool viewing editing text files
use terminal (grep find sed) search advanced replacements

#### text_editor:read
read file numbered lines
args path line_from (inclusive) line_to (inclusive) both optional
defaults first {{default_line_count}} lines if no range
usage:
~~~json
{
    "thoughts": [
        "I need to read..."
    ],
    "headline": "...",
    "tool_name": "text_editor:read",
    "tool_args": {
        "path": "/path/file.py",
        "line_from": 0,
        "line_to": 50
    }
}
~~~

#### text_editor:write
create overwrite entire file
args path content string
usage:
~~~json
{
    "thoughts": [
        "I need to write..."
    ],
    "headline": "...",
    "tool_name": "text_editor:write",
    "tool_args": {
        "path": "/path/file.py",
        "content": "import os\nprint('hello')\n"
    }
}
~~~

#### text_editor:patch
apply line edits existing file
args path edits (array of {from, to, content})
from and to are inclusive line numbers
{from:2, to:2, content:"x\n"} replace line 2
{from:1, to:3, content:"x\n"} replace lines 1-3
{from:2, to:2} delete line 2 (no content = delete)
{from:2, content:"x\n"} insert before line 2 (omit to = insert)
always original line numbers from read output dont adjust shifts
edits must not overlap
usage:
~~~json
{
    "thoughts": [
        "I need to patch..."
    ],
    "headline": "...",
    "tool_name": "text_editor:patch",
    "tool_args": {
        "path": "/path/file.py",
        "edits": [
            {"from": 1, "content": "import sys\n"},
            {"from": 5, "to": 5, "content": "    if x == 2:\n"}
        ]
    }
}
~~~
