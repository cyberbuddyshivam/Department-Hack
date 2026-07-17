import json

with open(r'C:\Users\Kaushal\.gemini\antigravity-ide\brain\9b78b7ad-0d23-4588-9cec-9f2f80c1925b\.system_generated\steps\103\content.md', encoding='utf-8') as f:
    content = f.read()

start = content.index('{"data":[')
data = json.loads(content[start:])['data']

free_text = []
for m in data:
    p = m.get('pricing', {})
    arch = m.get('architecture', {})
    out_mods = arch.get('output_modalities', [])
    in_mods = arch.get('input_modalities', [])
    is_free = p.get('prompt') == '0' and p.get('completion') == '0'
    is_text_out = 'text' in out_mods
    is_text_in = 'text' in in_mods
    exp = m.get('expiration_date')
    if is_free and is_text_out and is_text_in:
        ctx = m.get('context_length', 0)
        free_text.append({
            'id': m['id'],
            'name': m['name'],
            'ctx': ctx,
            'expires': exp,
            'in_mods': in_mods,
            'out_mods': out_mods,
        })

free_text.sort(key=lambda x: x['ctx'], reverse=True)
print("Found %d free text models:\n" % len(free_text))
for m in free_text:
    exp_str = " [EXPIRES %s]" % m['expires'] if m['expires'] else ''
    mods = '+'.join(m['in_mods'])
    print("  " + m['id'])
    print("    Name: " + m['name'] + exp_str)
    print("    Context: %d tokens | Input: %s" % (m['ctx'], mods))
    print()
