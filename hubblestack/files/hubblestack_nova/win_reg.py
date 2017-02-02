# -*- encoding: utf-8 -*-
'''

:maintainer: HubbleStack / madchills
:maturity: 2016.7.0
:platform: Windows
:requires: SaltStack

'''

from __future__ import absolute_import
import copy
import fnmatch
import logging
import salt.utils


log = logging.getLogger(__name__)
__virtualname__ = 'win_reg'

def __virtual__():
    if not salt.utils.is_windows():
        return False, 'This audit module only runs on windows'
    return True


def audit(data_list, tags, verbose=False, show_profile=False, debug=False):
    '''
    Runs auditpol on the local machine and audits the return data
    with the CIS yaml processed by __virtual__
    '''
    __data__ = {}
    for profile, data in data_list:
        if show_profile:
            _merge_yaml(__data__, data, profile)
        else:
            _merge_yaml(__data__, data)
    __tags__ = _get_tags(__data__)
    if debug:
        log.debug('registry audit __data__:')
        log.debug(__data__)
        log.debug('registry audit __tags__:')
        log.debug(__tags__)

    ret = {'Success': [], 'Failure': [], 'Controlled': []}
    for tag in __tags__:
        if fnmatch.fnmatch(tag, tags):
            for tag_data in __tags__[tag]:
                if 'control' in tag_data:
                    ret['Controlled'].append(tag_data)
                    continue
                name = tag_data['name']
                audit_type = tag_data['type']
                match_output = tag_data['match_output'].lower()
                reg_dict = _reg_path_splitter(name)

                # Blacklisted audit (do not include)
                if 'blacklist' in audit_type:
                    secret = _find_option_value_in_reg(reg_dict['hive'], reg_dict['key'], reg_dict['value'])
                    if secret:
                        ret['Failure'].append(tag_data)
                    else:
                        ret['Success'].append(tag_data)

                # Whitelisted audit (must include)
                if 'whitelist' in audit_type:
                    current = _find_option_value_in_reg(reg_dict['hive'], reg_dict['key'], reg_dict['value'])
                    if isinstance(current, list):
                        if False in current:
                            ret['Failure'].append(tag_data)
                        else:
                            for key in current:
                                secret = _translate_value_type(key, tag_data['value_type'], match_output)
                                if not secret:
                                    break
                            if secret:
                                ret['Success'].append(tag_data)
                            else:
                                ret['Failure'].append(tag_data)
                    if current:
                        secret = _translate_value_type(current, tag_data['value_type'], match_output)
                        if secret:
                            ret['Success'].append(tag_data)
                        else:
                            tag_data['value_found'] = current
                            ret['Failure'].append(tag_data)

                    else:
                        tag_data['value_found'] = None
                        ret['Failure'].append(tag_data)


    failure = []
    success = []
    controlled = []

    if not verbose:
        # Pull out just the tag and description
        tags_descriptions = set()

        for tag_data in ret['Failure']:
            tag = tag_data['tag']
            description = tag_data.get('description')
            if (tag, description) not in tags_descriptions:
                failure.append({tag: description})
                tags_descriptions.add((tag, description))

        tags_descriptions = set()

        for tag_data in ret['Success']:
            tag = tag_data['tag']
            description = tag_data.get('description')
            if (tag, description) not in tags_descriptions:
                success.append({tag: description})
                tags_descriptions.add((tag, description))

        control_reasons = set()

        for tag_data in ret['Controlled']:
            tag = tag_data['tag']
            control_reason = tag_data.get('control', '')
            description = tag_data.get('description')
            if (tag, description, control_reason) not in tags_descriptions:
                tag_dict = {'description': description,
                            'control': control_reason}
                controlled.append({tag: description})
                control_reasons.add((tag, description, control_reason))

    else:
        # Format verbose output as single-key dictionaries with tag as key
        for tag_data in ret['Failure']:
            tag = tag_data['tag']
            failure.append({tag: tag_data})

        for tag_data in ret['Success']:
            tag = tag_data['tag']
            success.append({tag: tag_data})

        for tag_data in ret['Controlled']:
            tag = tag_data['tag']
            controlled.append({tag: tag_data})

    ret['Controlled'] = controlled
    ret['Success'] = success
    ret['Failure'] = failure

    if not ret['Controlled']:
        ret.pop('Controlled')

    return ret


def _merge_yaml(ret, data, profile=None):
    '''
    Merge two yaml dicts together at the secedit:blacklist and
    secedit:whitelist level
    '''
    if __virtualname__ not in ret:
        ret[__virtualname__] = {}
    for topkey in ('blacklist', 'whitelist'):
        if topkey in data.get(__virtualname__, {}):
            if topkey not in ret[__virtualname__]:
                ret[__virtualname__][topkey] = []
            for key, val in data[__virtualname__][topkey].iteritems():
                if profile and isinstance(val, dict):
                    val['nova_profile'] = profile
                ret[__virtualname__][topkey].append({key: val})
    return ret


def _get_tags(data):
    '''
    Retrieve all the tags for this distro from the yaml
    '''
    ret = {}
    distro = __grains__.get('osfullname')
    for toplist, toplevel in data.get(__virtualname__, {}).iteritems():
        # secedit:whitelist
        for audit_dict in toplevel:
            for audit_id, audit_data in audit_dict.iteritems():
                # secedit:whitelist:PasswordComplexity
                tags_dict = audit_data.get('data', {})
                # secedit:whitelist:PasswordComplexity:data
                tags = None
                for osfinger in tags_dict:
                    if osfinger == '*':
                        continue
                    osfinger_list = [finger.strip() for finger in osfinger.split(',')]
                    for osfinger_glob in osfinger_list:
                        if fnmatch.fnmatch(distro, osfinger_glob):
                            tags = tags_dict.get(osfinger)
                            break
                    if tags is not None:
                        break
                # If we didn't find a match, check for a '*'
                if tags is None:
                    tags = tags_dict.get('*', [])
                # secedit:whitelist:PasswordComplexity:data:Windows 2012
                if isinstance(tags, dict):
                    # malformed yaml, convert to list of dicts
                    tmp = []
                    for name, tag in tags.iteritems():
                        tmp.append({name: tag})
                    tags = tmp
                for item in tags:
                    for name, tag in item.iteritems():
                        tag_data = {}
                        # Whitelist could have a dictionary, not a string
                        if isinstance(tag, dict):
                            tag_data = copy.deepcopy(tag)
                            tag = tag_data.pop('tag')
                        if tag not in ret:
                            ret[tag] = []
                        formatted_data = {'name': name,
                                          'tag': tag,
                                          'module': 'win_reg',
                                          'type': toplist}
                        formatted_data.update(tag_data)
                        formatted_data.update(audit_data)
                        formatted_data.pop('data')
                        ret[tag].append(formatted_data)
    return ret


def _reg_path_splitter(reg_path):
    dict_return = {}
    dict_return['hive'], temp = reg_path.split('\\', 1)
    dict_return['key'], dict_return['value'] = temp.rsplit('\\', 1)

    return dict_return



def _find_option_value_in_reg(reg_hive, reg_key, reg_value):
    '''
    helper function to retrieve Windows registry settings for a particular
    option
    '''
    if reg_hive.lower() in ('hku', 'hkey_users'):
        key_list = []
        ret_list = []
        sid_return = __salt__['cmd.run']('reg query hku').split('\n')
        for line in sid_return:
            if '\\' in line:
                key_list.append(line.split('\\')[1].strip())
        for sid in key_list:
            reg_key.replace('<SID>', sid)
            reg_result = __salt__['reg.read_value'](reg_hive, reg_key, reg_value)
            if reg_result['success']:
                ret_list.append(reg_result['vdata'])
            else:
                ret_list.append(False)
        if False in ret_list:
            return False
        else:
            return ret_list


    else:
        reg_result = __salt__['reg.read_value'](reg_hive, reg_key, reg_value)
        if reg_result['success']:
            return reg_result['vdata']
        else:
            return False


def _translate_evaluator(output):
    '''Helper function to return valid output you would find in the registry'''
    if 'enabled' in output:
        return '1'
    if 'disabled' in output:
        return '0'


def _translate_value_type(current, value, evaluator):
    evaluator = _translate_evaluator(evaluator)
    if 'all' in value:
        if current == evaluator:
            return True
        else:
            return False
    if 'domain' in value:
        pass
