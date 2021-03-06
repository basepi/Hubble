# -*- coding: utf-8 -*-
'''
Gather the system uuid via osquery
'''
import logging
import os
import salt.utils.path
import salt.modules.cmdmod

__salt__ = {'cmd.run_stdout': salt.modules.cmdmod.run_stdout}
log = logging.getLogger(__name__)


def get_system_uuid():
    '''
    Gather the system uuid via osquery and store it on disk.

    If osquery can't get a hardware-based value, it'll just randomly generate a new uuid every time.
    If that happens, fall back to the hubble_uuid.
    '''
    # Provides:
    #   system_uuid

    cached_system_uuid_path = os.path.join(os.path.dirname(__opts__['configfile']),
                                           'hubble_cached_system_uuid')
    previous_system_uuid = __opts__.get('system_uuid', None)
    hubble_uuid = __opts__.get('hubble_uuid', None)

    if not hubble_uuid:
        cached_hubble_uuid_path = os.path.join(os.path.dirname(__opts__['configfile']), 'hubble_cached_uuid')
        try:
            with open(cached_hubble_uuid_path, 'r') as f:
                hubble_uuid = f.read()
        except Exception:
            hubble_uuid = None

    # Get the system uuid via osquery. If it changes, fall back to hubble_uuid
    live_system_uuid = _get_uuid_from_system() or hubble_uuid

    if not live_system_uuid:
        # Can't reliably get system_uuid, and hubble_uuid not yet generated. Aborting.
        return {}

    try:
        if os.path.isfile(cached_system_uuid_path):
            with open(cached_system_uuid_path, 'r') as f:
                cached_system_uuid = f.read()
            # Check if it's changed out from under us -- problem!
            if cached_system_uuid != live_system_uuid:
                log.error("system_uuid on disk doesn't match live system value"
                          '\nLive: {0}\nOn Disk: {1}\nRewriting cached value'
                          .format(live_system_uuid, cached_system_uuid))
                _write_system_uuid_to_file(cached_system_uuid_path, live_system_uuid)
            return {'system_uuid': live_system_uuid}
        elif previous_system_uuid:
            log.error('system_uuid was previously cached, but the cached '
                      'file is no longer present: {0}'.format(cached_system_uuid_path))
        else:
            log.warning('no cache file found, caching system_uuid. '
                        '(probably not a problem)')
    except Exception:
        log.exception('Problem retrieving cached system uuid from file: {0}'
                      .format(cached_system_uuid_path))

    # Cache the system uuid if needed
    _write_system_uuid_to_file(cached_system_uuid_path, live_system_uuid)
    return {'system_uuid': live_system_uuid}


def _write_system_uuid_to_file(path, uuid):
    try:
        with open(path, 'w') as f:
            f.write(uuid)
    except Exception:
        log.exception('Problem writing cached system uuid to file: {0}'
                      .format(path))


def _get_uuid_from_system():
    query = '"SELECT uuid AS system_uuid FROM osquery_info;" --header=false --csv'

    # Prefer our /opt/osquery/osqueryi if present
    osqueryipaths = ('/opt/osquery/osqueryi', 'osqueryi', '/usr/bin/osqueryi')
    for path in osqueryipaths:
        if salt.utils.path.which(path):
            first_run = __salt__['cmd.run_stdout']('{0} {1}'.format(path, query), output_loglevel='quiet')
            first_run = str(first_run).upper()

            second_run = __salt__['cmd.run_stdout']('{0} {1}'.format(path, query), output_loglevel='quiet')
            second_run = str(second_run).upper()

            if len(first_run) == 36 and first_run == second_run:
                return first_run
            else:
                return None
    # If osquery isn't available, attempt to get uuid from /sys path (linux only)
    try:
        with open('/sys/devices/virtual/dmi/id/product_uuid', 'r') as f:
            file_uuid = f.read()
        file_uuid = str(file_uuid).upper()
        if len(file_uuid) == 36:
            return file_uuid
        else:
            return None
    except Exception:
        return None
