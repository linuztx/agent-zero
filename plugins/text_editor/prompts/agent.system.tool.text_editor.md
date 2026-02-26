### text_editor
native file read write patch tool with line numbers
prefer this over code_execution_tool for viewing and editing text files
use terminal (grep find sed) for searching files and advanced replacements

#### text_editor:read
read text file with line numbers
args: path (required), line_from (optional int, inclusive), line_to (optional int, inclusive)
line_from and line_to are both inclusive: line_to=5 means line 5 is included
defaults to first {{default_line_count}} lines if no range given
output shows numbered lines for precise patching
for binary files use terminal instead
usage:
~~~json
{
    "thoughts": [
        "Need to read file to understand structure..."
    ],
    "headline": "Reading file contents",
    "tool_name": "text_editor:read",
    "tool_args": {
        "path": "/path/to/file.py",
        "line_from": 0,
        "line_to": 50
    }
}
~~~

#### text_editor:write
create or replace entire file
args: path (required), content (required string)
usage:
~~~json
{
    "thoughts": [
        "Need to create new file..."
    ],
    "headline": "Creating new file",
    "tool_name": "text_editor:write",
    "tool_args": {
        "path": "/path/to/file.py",
        "content": "import os\nprint('hello')\n"
    }
}
~~~

#### text_editor:patch
apply line-based edits to existing file
args: path (required), edits (required array of {from, to, content})
from and to are both inclusive line numbers
{from:2, to:2, content:"new line\n"} replaces line 2
{from:2, to:4, content:"replacement\n"} replaces lines 2-4
{from:2, to:2} deletes line 2 (empty/missing content = delete)
to insert before line N without removing: omit to or set to:-1
{from:2, content:"inserted\n"} inserts before line 2
important: always use original line numbers from read output, do not adjust for shifts caused by other edits in same patch
edits must not overlap
usage:

1 replace a line
~~~json
{
    "thoughts": [
        "Need to fix syntax error on line 5..."
    ],
    "headline": "Fixing syntax error on line 5",
    "tool_name": "text_editor:patch",
    "tool_args": {
        "path": "/path/to/file.py",
        "edits": [
            {"from": 5, "to": 5, "content": "    if x == 2:\n"}
        ]
    }
}
~~~

2 insert + replace in one patch
~~~json
{
    "thoughts": [
        "Need to insert import at line 1 and fix line 5..."
    ],
    "headline": "Adding import and fixing syntax",
    "tool_name": "text_editor:patch",
    "tool_args": {
        "path": "/path/to/file.py",
        "edits": [
            {"from": 1, "content": "import sys\n"},
            {"from": 5, "to": 5, "content": "    if x == 2:\n"}
        ]
    }
}
~~~
