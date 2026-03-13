## system prompt includes
create files matching "{{name_pattern}}" pattern in workdir, always present in system prompt
use for: persistent instructions, behaviour rules, project context, reminders, style guides
files searched recursively in workdir, sorted alphabetically by full path
create/update/delete these files when user wants to change agent behaviour, remember instructions, or set persistent rules
{{if includes}}

### includes

{{includes}}
{{endif}}