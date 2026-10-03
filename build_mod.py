from pathlib import Path
import configparser
import io
import json
import re
import sys

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / '工具依赖'))
import ra2csf

GAME = Path(r'D:\Program\Game\RA2MD')
SOURCE = ROOT / '基础资源'
OUTPUT = ROOT / '安装文件'
MARKER = 'SGSTART'
COMPARATOR = '0100000003000000' + '0' * 48
TANKS = {'APOC', 'HTNK', 'LTNK', 'MGTK', 'MIND', 'MTNK',
         'ROBO', 'SREF', 'TELE', 'TNKD', 'TTNK', 'YTNK'}
DEFENSE_COUNT_KEYS = ('AlliedBaseDefenseCounts', 'SovietBaseDefenseCounts',
                      'ThirdBaseDefenseCounts')


def ini(text):
    result = configparser.ConfigParser(strict=False, interpolation=None,
                                       delimiters=('=',), allow_no_value=True,
                                       comment_prefixes=(';', '#', '//'),
                                       inline_comment_prefixes=(';',))
    result.optionxform = str
    result.read_string(text)
    return result


def section_span(text, section):
    match = re.search(r'(?m)^\[' + re.escape(section) + r'\][ \t]*\r?$', text)
    if match is None:
        raise ValueError(f'Missing section {section}')
    following = re.search(r'(?m)^\[', text[match.end():])
    end = match.end() + following.start() if following else len(text)
    return match.start(), end


def set_option(text, section, key, value):
    start, end = section_span(text, section)
    block, count = re.subn(r'(?m)^' + re.escape(key) + r'=[^\r\n]*',
                           key + '=' + value, text[start:end])
    if count != 1:
        raise ValueError(f'Expected exactly one {section}.{key}, found {count}')
    return text[:start] + block + text[end:]


def is_attack_script(ai, script):
    section = ai[script]
    for key, value in section.items():
        if not key.isdigit():
            continue
        action, parameter = map(int, value.split(','))
        if action == 0 and parameter not in {0, 8, 10, 11}:
            return True
        if action in {1, 46, 56, 57}:
            return True
        if action == 11 and parameter in {1, 15, 17, 29}:
            return True
    return False


def is_attack_trigger(ai, fields):
    if fields[13] == '1':
        return False
    for team_id in [fields[1], fields[14]]:
        if team_id in {'<none>', ''}:
            continue
        if team_id not in ai:
            raise ValueError(f'Unknown team {team_id}')
        if is_attack_script(ai, ai[team_id]['Script']):
            return True
    return False


def patch_rules(text):
    rules = ini(text)
    if MARKER in rules or MARKER in rules['BuildingTypes'].values():
        raise ValueError('Marker already registered')
    slot = max(map(int, rules['BuildingTypes'].keys())) + 1
    money_start, money_end = section_span(text, 'MultiplayerDialogSettings')
    money_block = text[money_start:money_end]
    for key, value in [('MinMoney', '5000'), ('MaxMoney', '500000')]:
        money_block, replacements = re.subn(r'(?m)^' + key + r'=[^\r\n]*',
                                             key + '=' + value, money_block)
        if replacements != 1:
            raise ValueError(f'Expected exactly one {key} setting')
    text = text[:money_start] + money_block + text[money_end:]
    defense_counts = {}
    for key in DEFENSE_COUNT_KEYS:
        if key not in rules['General']:
            continue
        old = [int(value.strip()) for value in rules['General'][key].split(',')]
        new = [value * 2 for value in old]
        start, end = section_span(text, 'General')
        block, count = re.subn(r'(?m)^(' + re.escape(key) + r'=)[0-9,]+',
                               lambda match: match.group(1) + ','.join(map(str, new)),
                               text[start:end])
        if count != 1:
            raise ValueError(f'Expected exactly one {key}')
        text = text[:start] + block + text[end:]
        defense_counts[key] = {'before': old, 'after': new}
    _, end = section_span(text, 'BuildingTypes')
    text = text[:end] + f'; Start Attack MOD\r\n{slot}={MARKER}\r\n\r\n' + text[end:]
    owner = rules['GAPOWR']['Owner']
    block = f'''
; Start Attack MOD - human-built attack permission marker
[{MARKER}]
UIName=Name:SGSTART
Name=Start Attack
Image=GASTRT
BuildCat=Tech
Prerequisite=
Strength=1000
Armor=steel
TechLevel=1
Adjacent=2
Sight=4
Owner={owner}
AIBasePlanningSide=0
AIBuildThis=no
Cost=100
Soylent=50
Points=0
Power=0
BuildLimit=1
BaseNormal=yes
IsBaseDefense=no
Capturable=no
Crewed=no
CanC4=no
ImmuneToPsionics=yes
Spyable=no
Drainable=no
Powered=no
PoweredSpecial=no
TogglePower=no
ThreatPosed=0
Explosion=TWLT070,S_BANG48,S_BRNL58,S_CLSN58,S_TUMU60
MaxDebris=2
MinDebris=0
DamageSmokeOffset=300,300,450
DieSound=PowerPlantDie
'''.replace('\n', '\r\n')
    return text.rstrip() + '\r\n' + block, slot, defense_counts


def patch_ai(text):
    ai = ini(text)
    changed = []
    substitutions = {}
    for trigger_id, value in ai['AITriggerTypes'].items():
        fields = value.split(',')
        if len(fields) != 18:
            raise ValueError(f'Unexpected trigger field count: {trigger_id}')
        if fields[10] != '1' or not is_attack_trigger(ai, fields):
            continue
        old = fields[4:7]
        fields[4:7] = ['0', MARKER, COMPARATOR]
        substitutions[trigger_id] = ','.join(fields)
        changed.append({'id': trigger_id, 'name': fields[0], 'previous_condition': old})
    start, end = section_span(text, 'AITriggerTypes')
    lines = text[start:end].splitlines(keepends=True)
    count = 0
    for index, line in enumerate(lines):
        key = line.split('=', 1)[0].strip()
        if key in substitutions:
            newline = '\r\n' if line.endswith('\r\n') else '\n'
            lines[index] = key + '=' + substitutions[key] + newline
            count += 1
    if count != len(substitutions):
        raise ValueError('Trigger replacement count mismatch')
    return text[:start] + ''.join(lines) + text[end:], changed


def strengthen_ai(text, rules_text):
    ai, rules = ini(text), ini(rules_text)
    team_ids = set(ai['TeamTypes'].values())
    defense = {team for team in team_ids
               if ai[team].get('IsBaseDefense', 'no').lower() == 'yes'}
    attack = {team for team in team_ids - defense
              if is_attack_script(ai, ai[team]['Script'])}
    neutral = team_ids - attack - defense
    roles = {'attack': attack, 'defense': defense, 'neutral': neutral}
    force_teams = {}
    for role, teams in roles.items():
        for team in teams:
            force_teams.setdefault(ai[team]['TaskForce'], {}).setdefault(role, set()).add(team)

    vehicle_types = set(rules['VehicleTypes'].values())
    infantry_types = set(rules['InfantryTypes'].values())
    assert TANKS & vehicle_types
    force_edits, team_edits, clones, limited = {}, {}, {}, []
    next_slot = max(map(int, ai['TaskForces'].keys())) + 1
    next_id = 0x6A000001
    for source, uses in sorted(force_teams.items()):
        active_roles = [role for role in ('attack', 'defense') if role in uses]
        if not active_roles:
            continue
        original_role = 'neutral' if 'neutral' in uses else 'defense' if 'defense' in uses else 'attack'
        for role in active_roles:
            target = source
            loads_passengers = role == 'attack' and any(
                any(key.isdigit() and action.split(',')[0] == '14'
                    for key, action in ai[ai[team]['Script']].items())
                for team in uses[role])
            if role != original_role:
                while f'{next_id:08X}-G' in ai or f'{next_id:08X}-G' in ai['TaskForces'].values():
                    next_id += 1
                target = f'{next_id:08X}-G'
                next_id += 1
                source_start, source_end = section_span(text, source)
                copy = text[source_start:source_end].replace('[' + source + ']', '[' + target + ']', 1)
                text = text.rstrip() + '\r\n\r\n; Start Attack MOD role-specific force\r\n' + copy.rstrip() + '\r\n'
                _, list_end = section_span(text, 'TaskForces')
                text = text[:list_end] + f'{next_slot}={target}\r\n' + text[list_end:]
                next_slot += 1
                clones[target] = source
                for team in sorted(uses[role]):
                    text = set_option(text, team, 'TaskForce', target)
                    team_edits[team] = target
            for key, entry in ai[source].items():
                if not key.isdigit():
                    continue
                count_text, unit = entry.split(',')
                count = int(count_text)
                new_count = count
                if role == 'defense':
                    new_count = count * 2
                elif unit == 'ZEP':
                    new_count = 5
                elif unit in infantry_types:
                    new_count = count * 4
                elif unit in TANKS:
                    if unit not in vehicle_types:
                        raise ValueError(f'Tank {unit} missing from VehicleTypes')
                    new_count = count * 3
                elif role == 'attack' and loads_passengers and unit in vehicle_types:
                    if int(rules[unit].get('Passengers', '0')) > 0:
                        new_count = count * 4
                if new_count != count and unit in rules:
                    build_limit = int(rules[unit].get('BuildLimit', '0'))
                    if build_limit > 0 and new_count > build_limit:
                        limited.append({'force': target, 'unit': unit, 'count': count,
                                        'build_limit': build_limit})
                        new_count = count
                if new_count != count:
                    text = set_option(text, target, key, f'{new_count},{unit}')
                    force_edits.setdefault(target, {})[key] = f'{new_count},{unit}'
    return text, {'attack_teams': len(attack), 'defense_teams': len(defense),
                  'force_edits': force_edits, 'team_edits': team_edits,
                  'clones': clones, 'build_limited': limited}


def patch_csf(path):
    head, entries = ra2csf.parse_file(str(path))
    if any(key.lower() == 'name:sgstart' for key, _, _, _ in entries):
        raise ValueError('CSF marker label already present')
    entries = list(entries) + [('Name:SGSTART', '开始进攻', None, 1)]
    header = list(head)
    header[2] += 1
    header[3] += 1
    out = io.BytesIO()
    # The package writer takes entries in key,value,extra,flag order.
    ra2csf.write(out, entries, head=header)
    return out.getvalue()


def verify(original_rules, original_ai, rules_text, ai_text, csf_data, changed,
           defense_counts, strength):
    before_rules, after_rules = ini(original_rules), ini(rules_text)
    before_ai, after_ai = ini(original_ai), ini(ai_text)
    for section in before_rules.sections():
        for key, value in before_rules[section].items():
            expected = {'MinMoney': '5000', 'MaxMoney': '500000'}.get(key, value) if section == 'MultiplayerDialogSettings' else value
            if section == 'General' and key in defense_counts:
                expected = ','.join(map(str, defense_counts[key]['after']))
            assert after_rules[section][key] == expected, (section, key)
    dialog = after_rules['MultiplayerDialogSettings']
    assert int(dialog['MinMoney']) == 5000
    assert int(dialog['MaxMoney']) == 500000
    assert (int(dialog['MaxMoney']) - int(dialog['MinMoney'])) % int(dialog['MoneyIncrement']) == 0
    assert list(after_rules['BuildingTypes'].values()).count(MARKER) == 1
    assert after_rules[MARKER]['Owner'] == before_rules['GAPOWR']['Owner']
    assert after_rules[MARKER]['AIBuildThis'].lower() == 'no'
    changed_ids = {entry['id'] for entry in changed}
    force_edits = strength['force_edits']
    team_edits = strength['team_edits']
    for section in before_ai.sections():
        for key, value in before_ai[section].items():
            new = after_ai[section][key]
            if section == 'AITriggerTypes' and key in changed_ids:
                old_fields, fields = value.split(','), new.split(',')
                assert fields[4:7] == ['0', MARKER, COMPARATOR]
                assert fields[:4] == old_fields[:4] and fields[7:] == old_fields[7:]
            elif section in force_edits and key in force_edits[section]:
                assert new == force_edits[section][key], (section, key)
            elif section in team_edits and key == 'TaskForce':
                assert new == team_edits[section], section
            else:
                assert new == value, (section, key)
    for section in after_ai.sections():
        if section in before_ai or section in strength['clones']:
            continue
        raise AssertionError(f'Unexpected AI section {section}')
    before_list = before_ai['TaskForces']
    after_list = after_ai['TaskForces']
    assert len(after_list) == len(before_list) + len(strength['clones'])
    for key, value in before_list.items():
        assert after_list[key] == value
    for clone, source in strength['clones'].items():
        assert clone in after_list.values()
        for key, value in before_ai[source].items():
            assert after_ai[clone][key] == force_edits.get(clone, {}).get(key, value)
    assert strength['attack_teams'] > 0 and strength['defense_teams'] > 0
    infantry = set(before_rules['InfantryTypes'].values())
    vehicles = set(before_rules['VehicleTypes'].values())
    for team in before_ai['TeamTypes'].values():
        old_team, new_team = before_ai[team], after_ai[team]
        defending = old_team.get('IsBaseDefense', 'no').lower() == 'yes'
        attacking = not defending and is_attack_script(before_ai, old_team['Script'])
        script = before_ai[old_team['Script']]
        loading = any(key.isdigit() and action.split(',')[0] == '14'
                      for key, action in script.items())
        old_force = before_ai[old_team['TaskForce']]
        new_force = after_ai[new_team['TaskForce']]
        for key, entry in old_force.items():
            if not key.isdigit():
                continue
            count_text, unit = entry.split(',')
            count = int(count_text)
            expected = count * 2 if defending else count
            if attacking:
                if unit == 'ZEP':
                    expected = 5
                elif unit in infantry:
                    expected = count * 4
                elif unit in TANKS:
                    expected = count * 3
                elif loading and unit in vehicles and int(before_rules[unit].get('Passengers', '0')) > 0:
                    expected = count * 4
            limit = int(before_rules[unit].get('BuildLimit', '0')) if unit in before_rules else 0
            if limit > 0 and expected > limit:
                expected = count
            assert new_force[key] == f'{expected},{unit}', (team, key)
    for key, value in after_ai['AITriggerTypes'].items():
        fields = value.split(',')
        if fields[10] == '1' and is_attack_trigger(after_ai, fields):
            assert fields[4:7] == ['0', MARKER, COMPARATOR], key
    header, entries = ra2csf.parse(io.BytesIO(csf_data))
    assert header[2] == len(entries)
    assert dict((v[0], v[1]) for v in entries)['Name:SGSTART'] == '开始进攻'
    assert sum(1 for entry in entries if entry[0].lower() == 'name:sgstart') == 1


def build(variants=('尤里的复仇', '原版红警2')):
    report = {}
    for title, suffix in [('尤里的复仇', 'md'), ('原版红警2', '')]:
        if title not in variants:
            continue
        rule_name, ai_name, csf_name = f'rules{suffix}.ini', f'ai{suffix}.ini', f'ra2{suffix}.csf'
        original_rules = (SOURCE / rule_name).read_bytes().decode('latin1')
        original_ai = (SOURCE / ai_name).read_bytes().decode('latin1')
        rules_text, slot, defense_counts = patch_rules(original_rules)
        ai_text, changed = patch_ai(original_ai)
        ai_text, strength = strengthen_ai(ai_text, original_rules)
        csf_source = SOURCE / csf_name
        if not csf_source.exists():
            state_path = GAME / 'StartAttackMOD' / f"state-{'YR' if suffix else 'RA2'}.json"
            state = json.loads(state_path.read_text(encoding='utf-8-sig')) if state_path.exists() else None
            candidate = Path(state['backupDirectory']) / csf_name if state and state['active'] else GAME / csf_name
            csf_source.write_bytes(candidate.read_bytes())
        csf_data = patch_csf(csf_source)
        _, old_strings = ra2csf.parse_file(str(csf_source))
        _, new_strings = ra2csf.parse(io.BytesIO(csf_data))
        old_by_name = {entry[0]: entry[1:] for entry in old_strings}
        new_by_name = {entry[0]: entry[1:] for entry in new_strings}
        assert all(new_by_name[key] == value for key, value in old_by_name.items())
        verify(original_rules, original_ai, rules_text, ai_text, csf_data, changed,
               defense_counts, strength)
        folder = OUTPUT / title
        folder.mkdir(parents=True, exist_ok=True)
        (folder / rule_name).write_bytes(rules_text.encode('latin1'))
        (folder / ai_name).write_bytes(ai_text.encode('latin1'))
        (folder / csf_name).write_bytes(csf_data)
        art_name = f'art{suffix}.ini'
        art_text = (SOURCE / art_name).read_bytes().decode('latin1')
        start, end = section_span(art_text, 'GAPOWR')
        custom_art = art_text[start:end].replace('[GAPOWR]', '[GASTRT]', 1).replace('Cameo=POWRICON', 'Cameo=SGSTICON', 1)
        art_result = art_text.rstrip() + '\r\n\r\n; Start Attack MOD custom cameo\r\n' + custom_art
        assert ini(art_result)['GASTRT']['Cameo'] == 'SGSTICON'
        assert ini(art_result)['GAPOWR']['Cameo'] == 'POWRICON'
        (folder / art_name).write_bytes(art_result.encode('latin1'))
        for sprite in (SOURCE / '图形').glob('g?powr.shp'):
            (folder / sprite.name.replace('powr', 'strt')).write_bytes(sprite.read_bytes())
        report[title] = {'starting_money_minimum': 5000, 'starting_money_maximum': 500000, 'building_slot': slot, 'attack_triggers_gated': len(changed),
                         'other_triggers_preserved': len(ini(original_ai)['AITriggerTypes'])-len(changed),
                         'attack_teams_strengthened': strength['attack_teams'],
                         'defense_teams_strengthened': strength['defense_teams'],
                         'attack_infantry_multiplier': 4, 'attack_tank_multiplier': 3,
                         'attack_kirov_per_team': 5, 'defense_team_multiplier': 2,
                         'transport_multiplier_for_embarking_teams': 4,
                         'defense_building_targets': defense_counts,
                         'build_limited_units': strength['build_limited'],
                         'task_force_clones': strength['clones'],
                         'changes': changed,
                         'verification': 'INI references, scoped team strengths and base defense counts, unchanged other fields, offensive triggers, CSF structure/name: passed',
                         'gameplay_tested': False}
        print(f'{title}: {len(changed)} attack triggers gated; {strength["attack_teams"]} attack teams and '
              f'{strength["defense_teams"]} defense teams strengthened; building index {slot}; structural checks passed')
    (ROOT / '构建与检查记录.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    build()
