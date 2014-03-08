import web
import json
import streamer

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
        return streamer.CurrentSong[0]
        
class song_list:
    def GET(self):
        web.header('Content-Type', 'application/json')
        
        streamer.MusicListLock.acquire()
        musicList = json.dumps(streamer.MusicList)
        streamer.MusicListLock.release()
        return musicList
        
class next_song:
    def POST(self, name):
        streamer.fillMusicBuffer(name)
        raise web.seeother('/')

web.internalerror = web.debugerror
if __name__ == '__main__':
    streamer.do_main()
    
    app = web.application(urls, globals())
    app.run()

