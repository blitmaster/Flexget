from __future__ import unicode_literals, division, absolute_import
import os
import logging
import re
import urlparse
import xmlrpclib

from flexget import plugin
from flexget.event import event
from flexget.entry import Entry
from flexget.utils.template import RenderError
 
from socket import error as socket_error

log = logging.getLogger('aria2bt')

# TODO: stop using torrent_info_hash[0:16] as the GID

class OutputAria2BT(object):

    """
    aria2 output plugin
    Version 1.0.0
    
    Configuration:
    server:     Where aria2 daemon is running. default 'localhost'
    port:       Port of that server. default '6800'
    username:   XML-RPC username set in aria2. default ''
    password:   XML-RPC password set in aria2. default ''
    uri:        URI of file to download. Can include inline Basic Auth para-
                meters and use jinja2 templating with any fields available
                in the entry. If you are using any of the dynamic renaming
                options below, the filename can be included in this setting
                using {{filename}}.
    exclude_samples:
                [yes|no] Exclude any files that include the word 'sample' in
                their name. default 'no'
    exclude_non_content:
                [yes|no] Exclude any non-content files, as defined by filename
                extensions not listed in file_exts. (See below.) default 'no'
    rename_content_files:
                [yes|no] If set, rename all content files (as defined by
                extensions listed in file_exts). default 'no'
    rename_template:
                If set, and rename_content_files is yes, all content files
                will be renamed using the value of this field as a template.
                Will be parsed with jinja2 and can include any fields
                available in the entry. default ''
    fix_year:   [yes|no] If yes, and the last four characters of the series
                name are numbers, enclose them in parantheses as they are
                likely a year. Example: Show Name 1995 S01E01.mkv would become
                Show Name (1995) S01E01.mkv. default 'yes'
    file_exts:  [list] File extensions of all files considered to be content
                files. Used to determine which files to rename or which files
                to exclude from download, with appropriate options set. (See
                above.)
                default: ['.mkv', '.avi', '.mp4', '.wmv', '.asf', '.divx',
                '.mov', '.mpg', '.rm']
    aria_config:
                "Parent folder" for any options to be passed directly to aria.
                Any command line option listed at
                http://aria2.sourceforge.net/manual/en/html/aria2c.html#options
                can be used by removing the two dashes (--) in front of the 
                command name, and changing key=value to key: value. All
                options will be treated as jinja2 templates and rendered prior
                to passing to aria2. default ''

    Sample configuration:
    aria2:
      server: myserver
      port: 6802
      exclude_samples: yes
      exclude_non_content: yes
      rename_content_files: yes
      rename_template: '{{series_name}} - {{series_id||lower}}'
      aria_config:
        max-connection-per-server: 4
        max-concurrent-downloads: 4
        split: 4
        file-allocation: none
        dir: "/Volumes/all_my_tv/{{series_name}}"
    """

    schema = {
        'type': 'object',
        'properties': {
            'server': {'type': 'string', 'default': 'localhost'},
            'port': {'type': 'integer', 'default': 6800},
            'username': {'type': 'string', 'default': ''},
            'password': {'type': 'string', 'default': ''},
            'uri': {'type': 'string'},
            'exclude_samples': {'type': 'boolean', 'default': False},
            'exclude_non_content': {'type': 'boolean', 'default': True},
            'rename_content_files': {'type': 'boolean', 'default': False},
            'fix_year': {'type': 'boolean', 'default': True},
            'rename_template': {'type': 'string', 'default': ''},
            'file_exts': {
                'type': 'array',
                'items': {'type': 'string'},
                'default': ['.mkv', '.avi', '.mp4', '.wmv', '.asf', '.divx', '.mov', '.mpg', '.rm']
            },
            'aria_config': {
                'type': 'object',
                'additionalProperties': {'oneOf': [{'type': 'string'}, {'type': 'integer'}, {'type': 'boolean'}]}
            }

        },
        'required': ['uri'],
        'additionalProperties': False
    }

    def pathscrub(self, dirty_path):
        path = dirty_path
        replaces = [['[:*?"<>| ]+', ' ']]  # Turn illegal characters into a space

        for search, replace in replaces:
            path = re.sub(search, replace, path)
        path = path.strip()
        return path

    def on_task_output(self, task, config):
        if 'aria_config' not in config:
            config['aria_config'] = {}
        if 'uri' not in config:
            raise plugin.PluginError('uri (path to folder containing file(s) on server) is required.', log)
        if 'dir' not in config['aria_config']:
            raise plugin.PluginError('dir (destination directory) is required.', log)
        if config['rename_content_files'] and not config['rename_template']:
            raise plugin.PluginError('When using rename_content_files, you must specify a rename_template.', log)
        if config['username'] and not config['password']:
            raise plugin.PluginError('If you specify an aria2 username, you must specify a password.')

        try:
            userpass = ''
            if config['username']:
                userpass = '%s:%s@' % (config['username'], config['password'])
            baseurl = 'http://%s%s:%s/rpc' % (userpass, config['server'], config['port'])
            log.debug('base url: %s' % baseurl)
            s = xmlrpclib.ServerProxy(baseurl)
            log.info('Connected to daemon at ' + baseurl + '.')
        except xmlrpclib.ProtocolError as err:
            raise plugin.PluginError('Could not connect to aria2 at %s. Protocol error %s: %s'
                                     % (baseurl, err.errcode, err.errmsg), log)
        except xmlrpclib.Fault as err:
            raise plugin.PluginError('XML-RPC fault: Unable to connect to aria2 daemon at %s: %s'
                                     % (baseurl, err.faultString), log)
        except socket_error as (error, msg):
            raise plugin.PluginError('Socket connection issue with aria2 daemon at %s: %s'
                                     % (baseurl, msg), log)
        except:
            raise plugin.PluginError('Unidentified error during connection to aria2 daemon at %s' % baseurl, log)

        # loop entries
        for entry in task.accepted:
            config['aria_dir'] = config['aria_config']['dir']
            #if 'aria_gid' in entry:
            #    config['aria_config']['gid'] = entry['aria_gid']
            #elif 'torrent_info_hash' in entry:
            #    config['aria_config']['gid'] = entry['torrent_info_hash'][0:16]
            #elif 'gid' in config['aria_config']:
            #    del(config['aria_config']['gid'])
            if 'gid' in config['aria_config']:
                del(config['aria_config']['gid'])

            if 'select-file' in config['aria_config']:
                del(config['aria_config']['select-file'])
            if 'index-out' in config['aria_config']:
                del(config['aria_config']['index-out'])

            if 'content_files' not in entry:
                raise plugin.PluginError('no content_files in entry!', log)
            else:
                if not isinstance(entry['content_files'], list):
                    entry['content_files'] = [entry['content_files']]


            new_download = 1

            arrfiles = []
            arrselectfiles = []

            if new_download == 1:
                torrentNdx = 0;
                counter = 0
                for cur_file in entry['content_files']:
                    torrentNdx += 1
                    # reset the 'dir' or it will only be rendered on the first loop
                    config['aria_config']['dir'] = config['aria_dir']
    
                    cur_filename = cur_file.split('/')[-1]
    
                    file_dot = cur_filename.rfind(".")
                    file_ext = cur_filename[file_dot:]
    
                    if config['exclude_samples'] == True:
                        # remove sample files from download list
                        if cur_filename.lower().find('sample') > -1:
                            continue
    
                    if file_ext not in config['file_exts']:
                        if config['exclude_non_content'] == True:
                            # don't download non-content files, like nfos - definable in file_exts
                            continue
    
                    arrselectfiles += [str(torrentNdx)]
                    if config['rename_content_files']:
                        try:
                            strfile = str(torrentNdx) + '=' + self.pathscrub(entry.render(config['rename_template'])) + file_ext
                            arrfiles += [strfile]
                            log.verbose(arrfiles)
                        except RenderError as e:
                            log.error('Could not rename file %s: %s.' % (cur_filename, e))
                            continue
                    #else:
                    #    config['aria_config']['out'] = cur_filename
    
                log.debug('Adding new file')
                try:
                    cur_uri = entry.render(config['uri'])
                    log.verbose('uri: %s' % cur_uri)
                except RenderError as e:
                    raise plugin.PluginError('Unable to render uri: %s' % e)
                try:
                    for key, value in config['aria_config'].iteritems():
                        log.trace('rendering %s: %s' % (key, value))
                        config['aria_config'][key] = entry.render(unicode(value))
                    
                    config['aria_config']['index-out'] = arrfiles
                    config['aria_config']['select-file'] = arrselectfiles

                    log.debug('dir: %s' % config['aria_config']['dir'])
                    if not task.manager.options.test:
                        log.debug(xmlrpclib.dumps( ([cur_uri], config['aria_config']), 'addUri' ))
                        r = s.aria2.addUri([cur_uri], config['aria_config'])
                    else:
                        if 'gid' not in config['aria_config']:
                            r = '1234567890123456'
                        else:
                            r = config['aria_config']['gid']
                    log.info('%s successfully added to aria2 with gid %s.' % (cur_uri, r))
                except xmlrpclib.Fault as err:
                    raise plugin.PluginError('aria2 response to add URI request: %s' % err.faultString, log)
                except socket_error as (error, msg):
                    raise plugin.PluginError('Socket connection issue with aria2 daemon at %s: %s'
                                             % (baseurl, msg), log)
                except RenderError as e:
                    raise plugin.PluginError('Unable to render one of the fields being passed to aria2:'
                                             '%s' % e)


@event('plugin.register')
def register_plugin():
    plugin.register(OutputAria2BT, 'aria2bt', api_ver=2)
