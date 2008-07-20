import re
import logging

__pychecker__ = 'unusednames=parser'

log = logging.getLogger('remove_trackers')

class RemoveTrackers:

    """
        Removes trackers from torrent files using regexp matching.

        Configuration example:

        remove_trackers:
          - moviex

        This will remove all trackers that contain text moviex in their url.
        TIP: You can use global section in configuration to make this enabled on all feeds.
    """

    def register(self, manager, parser):
        manager.register(event='modify', keyword='remove_trackers', callback=self.remove)

    def validate(self, config):
        from validator import ListValidator
        remove = ListValidator()
        remove.accept(str)
        remove.validate(config)
        return remove.errors.messages

    def remove(self, feed):
        for entry in feed.entries:
            if entry.has_key('torrent'):
                trackers = entry['torrent'].get_multitrackers()
                for tracker in trackers:
                    for regexp in feed.config.get('remove_trackers', []):
                        if re.search(regexp, tracker, re.IGNORECASE|re.UNICODE):
                            log.debug('remove_trackers removing %s because of %s' % (tracker, regexp))
                            # remove tracker
                            entry['torrent'].remove_multitracker(tracker)
                            log.info('Removed %s' % tracker)
                            # re-write data into a file
                            f = open(entry['file'], 'r+')
                            f.write(entry['torrent'].encode())
                            f.close()
