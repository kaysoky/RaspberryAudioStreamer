import os, sys, errno
import traceback
import thread, random, time, json
from subprocess import call
from threading import Lock
from Queue import Queue

import webbrowser
from dropbox import client
from dropbox.rest import ErrorResponse, RESTSocketError
from httplib import BadStatusLine

###############################################################################
##                                  Globals                                  ##
###############################################################################

APP_KEY = 'kpvw9op95082dzj'
APP_SECRET = 'm953vw8r3mz45gq'
MUSIC_CACHE = os.path.expanduser('./.cache')
TOKEN_FILE = "token.txt"
INDEX_FILE = "index.json"
MUSIC_LIST_UPDATE_TIME = 60 * 60 # 1 hour
MUSIC_BUFFER_SIZE = 3
GENERAL_SLEEP_TIME = 15
MUSIC_READ_CHUNK_SIZE = 1024

Streamer = None
StreamerLock = Lock()
MusicList = []
MusicListLock = Lock()
MusicQueue = Queue()
UniqueExceptionsLock = Lock()
UniqueExceptions = set()

# Only used by the music player thread
CurrentSong = [None]

###############################################################################
##                              Thread Helpers                               ##
###############################################################################

def fetchMusicList():
    """
    Traverses down two levels into the /Ambience folder
      and builds a list of all MP3's found.
    Replaces MusicList with the new list.
    """

    newMusicList = []

    StreamerLock.acquire()
    artists = None
    try:
        artists = Streamer.metadata('/Ambience')['contents']
    finally:
        StreamerLock.release()
    if artists is None: return

    for artist in artists:
        if not artist.get('is_dir', False) or 'path' not in artist:
            continue

        StreamerLock.acquire()
        music = None
        try:
            music = Streamer.metadata(artist['path'])['contents']
        finally:
            StreamerLock.release()
        if music is None: continue

        for audio in music:
            # Only keep MP3's
            if audio.get('mime_type', 'Something Else') != u'audio/mpeg':
                continue

            if 'path' in audio:
                newMusicList.append(audio['path'])

    # Copy the list over
    MusicListLock.acquire()
    del MusicList[:]
    for item in newMusicList:
        MusicList.append(item)

    # And save the list in a file
    with open(INDEX_FILE, 'w') as file:
        json.dump(newMusicList, file)
    MusicListLock.release()
    print '[Music list updated]'


def fillMusicBuffer(musicSource=None):
    """
    Navigates the music list at random and downloads music to play.
    """

    # Choose a song
    if musicSource is None:
        if len(MusicList) <= 0:
            return
        MusicListLock.acquire()
        try:
            musicSource = MusicList[random.randrange(len(MusicList))]
        finally:
            MusicListLock.release()

    # Download the song
    musicDestPath = os.path.join(MUSIC_CACHE, 
                                 os.path.basename(os.path.dirname(musicSource)), 
                                 os.path.basename(musicSource))
    try: os.makedirs(os.path.dirname(musicDestPath))
    except: pass
    musicDest = open(musicDestPath, "wb")
    StreamerLock.acquire()
    try:
        source, metadata = Streamer.get_file_and_metadata(musicSource)
        musicDest.write(source.read())
        musicDest.close()
        source.close()

        # Add it to the playlist
        MusicQueue.put(musicDestPath)
    finally:
        StreamerLock.release()


def handleException():
    UniqueExceptionsLock.acquire()
    exception = traceback.format_exc()
    if exception not in UniqueExceptions:
        UniqueExceptions.add(exception)
        print exception
    UniqueExceptionsLock.release()


###############################################################################
##                              Authentication                               ##
###############################################################################

try:
    # Token is saved locally
    token = open(TOKEN_FILE).read()
    Streamer = client.DropboxClient(token)
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
    Streamer = client.DropboxClient(access_token)

###############################################################################
##                               Music Player                                ##
###############################################################################

def updateMusicList():
    try:
        with open(INDEX_FILE, 'r') as file:
            loadedMusicList = json.load(file)
            for item in loadedMusicList:
                MusicList.append(item)
        print "Loaded music list"
        time.sleep(MUSIC_LIST_UPDATE_TIME)
    except:
        handleException()

    while True:
        try:
            fetchMusicList()
        except:
            handleException()

        # Keep trying if the fetch fails
        if len(MusicList) <= 0:
            continue

        time.sleep(MUSIC_LIST_UPDATE_TIME)

def updateMusicBuffer():
    while True:
        if MusicQueue.qsize() < MUSIC_BUFFER_SIZE:
            try:
                fillMusicBuffer()
            except:
                handleException()
        else:
            time.sleep(GENERAL_SLEEP_TIME)

def playMusic():
    while True:
        try:
            if MusicQueue.qsize() > 0:
                nextSong = MusicQueue.get()
                CurrentSong[0] = nextSong
                call(["mpg123", "--buffer", "4096", "--smooth", "--quiet", nextSong])
                os.remove(nextSong)
            else:
                time.sleep(0)
        except KeyboardInterrupt:
            exit()
        except SystemExit:
            print "Exit caught"
        except:
            handleException()

def do_main(async=True):
    # Set the volume to 100%
    call(['amixer', 'sset', "'PCM'", '100%'])

    # Empty the cache of old music
    call(['rm', '-r', MUSIC_CACHE])

    # Make the cache directory
    try: os.makedirs(MUSIC_CACHE)
    except: pass

    # Start all the background threads
    thread.start_new_thread(updateMusicList, ())
    thread.start_new_thread(updateMusicBuffer, ())
    if async:
        thread.start_new_thread(playMusic, ())
    else:
        playMusic()

if __name__ == '__main__':
    do_main(False)
