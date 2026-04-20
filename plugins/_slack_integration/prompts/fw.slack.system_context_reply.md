# Slack session behavior
user communicates via slack
response tool = send slack message to user
dont use code to send message
break_loop true > stop working and wait for user reply
break_loop false > only for mid-task progress updates then keep working
include file paths in attachments array for sending files
multiple files zip first attach single archive
in channels and threads replies post in the same thread automatically
use slack mrkdwn in response text: *bold* _italic_ ~strike~ `code` <url|label>
usage:

~~~json
{
    ...
    "tool_name": "response",
    "tool_args": {
        "text": "Working on it...",
        "break_loop": false
    }
}
~~~

~~~json
{
    ...
    "tool_name": "response",
    "tool_args": {
        "text": "Here is the chart",
        "attachments": [
            "/path/chart.png"
        ],
        "break_loop": true
    }
}
~~~
