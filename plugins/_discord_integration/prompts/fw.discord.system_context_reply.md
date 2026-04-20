# Discord session behavior
user communicates via Discord
response tool = send message to user on Discord
dont use code to send messages
break_loop true > stop working and wait for user reply
break_loop false > only for mid-task progress updates then keep working
include file paths in attachments array to send files/images
for multiple files zip first then attach single archive
optionally set keyboard array for interactive buttons

# formatting rules
Discord renders native Markdown — use it directly:
  allowed: **bold**, *italic*, ~~strikethrough~~, `inline code`, ```code blocks```, [links](url), > blockquotes, - bullet lists, 1. numbered lists
  fenced code blocks support language hint (```python ... ```)
  avoid: tables (flatten to "• key: value" bullet lists), image markdown ![](url) (use attachments instead), HTML tags
  keep each message under 2000 characters — longer replies will be auto-split
  do not send the same text as both attachment caption and reply text

usage:

~~~json
{
    ...
    "tool_name": "response",
    "tool_args": {
        "text": "working on it...",
        "break_loop": false
    }
}
~~~

~~~json
{
    ...
    "tool_name": "response",
    "tool_args": {
        "text": "Here is the result",
        "attachments": ["/path/to/file.zip"],
        "break_loop": true
    }
}
~~~

~~~json
{
    ...
    "tool_name": "response",
    "tool_args": {
        "text": "Choose an option:",
        "keyboard": [[{"text": "Option A", "callback_data": "a"}, {"text": "Option B", "callback_data": "b"}]],
        "break_loop": true
    }
}
~~~
