import json
import re

def parse_log():
    with open('test_matrix.log', 'r', encoding='utf-16') as f:
        content = f.read()
    
    cases = []
    blocks = re.split(r'### ', content)
    for block in blocks[1:]:
        lines = block.strip().split('\n')
        name = lines[0].strip()
        
        json_str = ""
        in_json = False
        for line in lines[1:]:
            if line.startswith('```json'):
                in_json = True
                continue
            if line.startswith('```'):
                in_json = False
                continue
            if in_json:
                json_str += line + '\n'
        
        # Concurrent ones have two json outputs
        jsons = []
        import json.decoder
        idx = 0
        while idx < len(json_str):
            try:
                obj, new_idx = json.decoder.JSONDecoder().raw_decode(json_str[idx:])
                jsons.append(obj)
                idx += new_idx
                while idx < len(json_str) and json_str[idx].isspace():
                    idx += 1
            except json.JSONDecodeError:
                break
                
        for i, data in enumerate(jsons):
            cases.append((f"{name} (Part {i+1})" if len(jsons) > 1 else name, data))
            
    for name, data in cases:
        print(f"\n--- {name} ---")
        fd = data.get('final_decision', {})
        trace = data.get('agent_trace', [])
        md = data.get('map_data', {})
        
        ss = fd.get('severity_score')
        at = fd.get('ambulance', {}).get('type')
        hosp = fd.get('hospital', {}).get('name')
        hrr = fd.get('requires_human_review')
        eta1 = md.get('ambulance', {}).get('eta_to_incident_minutes')
        eta2 = md.get('hospital', {}).get('eta_incident_to_hospital_minutes')
        
        confs = [t.get('confidence') for t in trace if t.get('confidence') is not None]
        min_conf = min(confs) if confs else None
        
        print(f"Severity: {ss}, Ambulance: {at}, Hospital: {hosp}")
        print(f"ETA1 (Amb->Inc): {eta1}, ETA2 (Inc->Hosp): {eta2}")
        print(f"Human Review: {hrr}, Lowest Conf: {min_conf}")
        low_agents = [f"{t['agent_name']}({t.get('confidence')})" for t in trace if t.get('confidence', 1) < 0.6]
        print(f"Low conf agents: {low_agents}")
        for t in trace:
            if t['agent_name'] == 'dispatch':
                print(f"Dispatch type mismatch: {t['result'].get('type_mismatch')}")

parse_log()
