import web
import json
from streamer import DropboxAudioStreamer

urls = (
    '/', 'generic_getter', 
    '/static/(.*)', 'generic_getter', 
    '/song/current', 'current_song', 
    '/song/list', 'song_list', 
    '/song/next(/.*)', 'next_song'
)

class generic_getter:
    def GET(self, name=None):
        if name is None:
            name = 'index.html'
        with open('static/%s' % name, 'r') as f:
            return f.read()

class current_song:
    def GET(self):
        web.header('Content-Type', 'application/text')
        return web.streamer.CurrentSong
        
class song_list:
    def GET(self):
        web.header('Content-Type', 'application/json')
        
        web.streamer.MusicListLock.acquire()
        musicList = json.dumps(web.streamer.MusicList)
        web.streamer.MusicListLock.release()
        return musicList
        
class next_song:
    def POST(self, name):
        web.streamer.MusicBufferer.addSong(name)
        raise web.seeother('/')

web.internalerror = web.debugerror
if __name__ == '__main__':
    web.streamer = DropboxAudioStreamer()
    web.streamer.start()
    
    app = web.application(urls, globals())
    app.run()

