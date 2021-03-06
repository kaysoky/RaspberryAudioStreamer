import os
import sys
import errno
import traceback
import thread
import random
import time
from datetime import datetime
import json
from subprocess import call
from threading import Thread, Lock
from Queue import Queue, Empty

import webbrowser
from dropbox import client

# Dropbox application specific data
APP_KEY = 'kpvw9op95082dzj'
APP_SECRET = 'm953vw8r3mz45gq'
TOKEN_FILE = "token.txt"
MUSIC_FOLDER = '/Ambience'

# Caching locations to improve performance/resource utilization
MUSIC_CACHE = os.path.expanduser('./.cache')
INDEX_FILE = "index.json"
MUSIC_BUFFER_SIZE = 3
MUSIC_READ_CHUNK_SIZE = 1024

# Timing constants
MUSIC_LIST_UPDATE_TIME = 60 * 60 # 1 hour
GENERAL_SLEEP_TIME = 15
RECENT_MUSIC_DAYS = 7

class MusicListUpdater(Thread):
    def __init__(self, shared):
        Thread.__init__(self)
        self.shared = shared

    def run(self):
        # Load in a cached music list
        try:
            self.shared.MusicListLock.acquire()
            with open(INDEX_FILE, 'r') as file:
                self.shared.MusicList = json.load(file)

            print "[Loaded music list]"
        except:
            traceback.print_exc()

        finally:
            self.shared.MusicListLock.release()
        
        if len(self.shared.MusicList) > 0:
            time.sleep(MUSIC_LIST_UPDATE_TIME)

        while True:
            try:
                self._perform_update()
            except:
                traceback.print_exc()
                time.sleep(GENERAL_SLEEP_TIME)

            # Keep trying if the fetch fails
            if len(self.shared.MusicList) <= 0:
                continue

            time.sleep(MUSIC_LIST_UPDATE_TIME)

    def _perform_update(self):
        """
        Traverses down two levels into the music folder
          and builds a list of all MP3's found.
        Replaces MusicList with the new list.
        """

        # Initialize the new list
        newMusicList = []
        newRecentList = []

        try:
            self.shared.DropboxLock.acquire()

            # Fetch all the metadata about the music-containing folder
            currentTime = datetime.now()
            cursor = None
            delta = self.shared.Dropbox.delta(cursor, MUSIC_FOLDER)

            while len(delta['entries']) > 0 or delta['has_more']:
                for path, metadata in delta['entries']:
                    if metadata is None:
                        continue

                    if metadata.get('mime_type', 'Something Else') != u'audio/mpeg':
                        continue

                    # Append the properly capitalized name
                    path = metadata.get('path', path)
                    newMusicList.append(path)
                
                    # Get the modification date
                    modified = metadata.get('modified', 'Tue, 19 Jul 2011 21:55:38 +0000')[:-6]
                    modified = datetime.strptime(modified, '%a, %d %b %Y %H:%M:%S')
                    if (currentTime - modified).days < RECENT_MUSIC_DAYS:
                        newRecentList.append(path)

                cursor = delta['cursor']
                delta = self.shared.Dropbox.delta(cursor, MUSIC_FOLDER)
        except:
            traceback.print_exc()

        finally:
            self.shared.DropboxLock.release()

        # Copy the list over
        try:
            self.shared.MusicListLock.acquire()
            self.shared.MusicList = newMusicList
            self.shared.RecentMusicList = newRecentList

            # Save the list in a file
            with open(INDEX_FILE, 'w') as file:
                json.dump(newMusicList, file)
            print '[Music list updated]'

        finally:
            self.shared.MusicListLock.release()

class MusicBufferer(Thread):
    def __init__(self, shared):
        Thread.__init__(self)
        self.shared = shared
        self.queue = Queue()

    def run(self):
        while True:
            if self.shared.MusicQueue.qsize() < MUSIC_BUFFER_SIZE:
                try:
                    if self.queue.qsize() > 0:
                        self._downloadSong()
                    else:
                        self.addSong()
                except:
                    traceback.print_exc()
                    time.sleep(GENERAL_SLEEP_TIME)
            else:
                time.sleep(GENERAL_SLEEP_TIME)

    def addSong(self, musicSource=None):
        """
        Navigates the music list at random and chooses a song to download
            There is a bias towards more recent music
        If the song is provided, that song is added instead
        """

        try:
            self.shared.MusicListLock.acquire()
            # Choose a song
            if musicSource is None:
                if len(self.shared.MusicList) <= 0:
                    return
                    
                # Get a random number with a bias towards the newer stuff
                musicLength = len(self.shared.MusicList)
                recentLength = len(self.shared.RecentMusicList)
                idx = random.randrange(musicLength + min(musicLength / 2, recentLength * 10))
                if idx < musicLength:
                    musicSource = self.shared.MusicList[idx]
                else:
                    idx = idx % recentLength
                    musicSource = self.shared.RecentMusicList[idx]

            # Queue the song for download
            self.queue.put(musicSource)

        finally:
            self.shared.MusicListLock.release()

    def _downloadSong(self):
        """
        Pops a song off the internal queue and downloads it
        """

        # Determine where to download the song
        try:
            musicSource = self.queue.get(False)
        except Empty:
            return
        musicDestPath = os.path.join(MUSIC_CACHE,
                                     os.path.basename(os.path.dirname(musicSource)),
                                     os.path.basename(musicSource))
        try: os.makedirs(os.path.dirname(musicDestPath))
        except: pass

        # Download the song
        musicDest = open(musicDestPath, "wb")
        try:
            self.shared.DropboxLock.acquire()
            source, metadata = self.shared.Dropbox.get_file_and_metadata(musicSource)
            musicDest.write(source.read())
            musicDest.close()
            source.close()

            # Add it to the playlist
            self.shared.MusicQueue.put(musicDestPath)

        finally:
            self.shared.DropboxLock.release()

class MusicPlayer(Thread):
    def __init__(self, shared):
        Thread.__init__(self)
        self.shared = shared

    def run(self):
        while True:
            try:
                if self.shared.MusicQueue.qsize() > 0:
                    self.shared.CurrentSong = self.shared.MusicQueue.get()
                    call(["mpg123", "--buffer", "4096", "--smooth", "--quiet", self.shared.CurrentSong])
                    os.remove(self.shared.CurrentSong)
                else:
                    time.sleep(GENERAL_SLEEP_TIME)
            except KeyboardInterrupt:
                exit()
            except:
                traceback.print_exc()

class DropboxAudioStreamer():
    def __init__(self):
        """
        Initializes the audio streamer and connects to Dropbox
        """

        self.Dropbox = None
        self.DropboxLock = Lock()
        self.MusicList = []
        self.RecentMusicList = []
        self.MusicListLock = Lock()
        self.MusicQueue = Queue()
        self.CurrentSong = None

        # Connect to Dropbox
        try:
            # Token is saved locally
            token = open(TOKEN_FILE).read()
            self.Dropbox = client.DropboxClient(token)
            print "[loaded access token]"
        except IOError:
            # Token not available, so login
            flow = client.DropboxOAuth2FlowNoRedirect(APP_KEY, APP_SECRET)
            authorize_url = flow.start()
            webbrowser.open(authorize_url)
            code = raw_input("Enter the authorization code here: ").strip()

            try:
                access_token, user_id = flow.finish(code)
            except ErrorResponse:
                handleException()
                exit()

            with open(TOKEN_FILE, 'w') as f:
                f.write(access_token)
            self.Dropbox = client.DropboxClient(access_token)

        # Set the volume to 100%
        call(['amixer', 'sset', "'PCM'", '100%'])

        # Empty the cache of old music
        call(['rm', '-r', MUSIC_CACHE])

        # Make the cache directory
        try: os.makedirs(MUSIC_CACHE)
        except: pass

        # Start the child threads
        self.MusicListUpdater = MusicListUpdater(self)
        self.MusicListUpdater.daemon = True
        self.MusicListUpdater.start()

        self.MusicBufferer = MusicBufferer(self)
        self.MusicBufferer.daemon = True
        self.MusicBufferer.start()

    def start(self, async=True):
        self.MusicPlayer = MusicPlayer(self)
        if async:
            self.MusicPlayer.daemon = True
            self.MusicPlayer.start()
        else:
            self.MusicPlayer.run()

if __name__ == '__main__':
    DropboxAudioStreamer().start(False)
