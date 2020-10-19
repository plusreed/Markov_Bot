""" Class for the Telegram Bot """

# Import libraries
import json
from socket import timeout
from time import sleep
from traceback import print_exc
import urllib

from config import USER_AGENT

custom_urlopen = lambda u,**kw:urllib.request.urlopen(
    urllib.request.Request(u, headers={'User-Agent': USER_AGENT}),**kw)

class TelegramBot():
    class attribute_dict():
        def __init__(self, data):
            self.__data__ = data
        def __getattr__(self, index):
            if index == "__data__": return object.__setattr__(self, "__data__")
            try:
                return self.__getitem__(index)
            except KeyError:
                raise AttributeError
        def __getitem__(self, index):
            return self.__data__[index]
        def __setattr__(self, index, value):
            if index == "__data__": return object.__setattr__(self, "__data__", value)
            self.__setitem__(index)
        def __setitem__(self, index, value):
            self.__data__[index] = value
        def __delattr__(self, index, value):
            if index == "__data__": return object.__delattr__(self, "__data__", value)
            self.__delitem__(index)
        def __delitem__(self, index):
            del self.__data__[index]
        def __repr__(self):
            return repr(self.__data__)
        def __iter__(self):
            return iter(self.__data__)
        def __len__(self):
            return len(self.__data__)
        def keys(self):
            return self.__data__.keys()
        def has(self, key):
            return key in self.__data__.keys() and self.__data__[key] != None
    def __init__(self, token):
        self.token = token
        self.retry = 0
    def __getattr__(self, attr):
        return self.func_wrapper(attr)
    def get_url(self, fname, **kw):
        url_par={}
        for key in kw.keys():
            if kw[key] != None:
                url_par[key] = urllib.parse.quote_plus(TelegramBot.escape(kw[key]))
        return (url_par,("https://api.telegram.org/bot" + self.token + "/" + (
            fname.replace("__UNSAFE","") if fname.endswith("__UNSAFE") else fname) + "?" +
                "&".join(map(lambda x:x+"="+url_par[x],url_par.keys()))))
    
    @staticmethod
    def default_urlopen(u):
        with custom_urlopen(u,timeout=90) as f:
            raw = f.read().decode('utf-8')
        return raw
    def func_wrapper(self, fname):
        def func(self, unsafe, _urlopen_hook=bot.default_urlopen, **kw):
            url_par, url = self.get_url(fname, **kw)
            RETRY = True
            while RETRY:
                try:
                    raw = _urlopen_hook(url)
                    RETRY = False
                except urllib.error.HTTPError as e:
                    if "bad request" in str(e).lower() and not unsafe:
                        print(fname, url)
                        print(json.dumps(url_par))
                        print(e.read().decode('utf-8'))
                        print_exc()
                        return
                    elif "forbidden" in str(e).lower() and not unsafe:
                        print(fname, url)
                        print(json.dumps(url_par))
                        print(e.read().decode('utf-8'))
                        print_exc()
                        return
                    else:
                        raise e                    
                except timeout:
                    if unsafe:
                        raise ValueError("timeout")
                    else:
                        print("timeout!")
                        sleep(1)
                except BaseException as e:
                    print(str(e))
                    sleep(0.5)
                    if "too many requests" in str(e).lower():
                        self.retry += 1
                        sleep(self.retry * 5)
                    elif ("unreachable" in str(e).lower()) or (
                        "bad gateway" in str(e).lower()) or (
                        "name or service not known" in str(e).lower()) or (
                        "network" in str(e).lower()) or (
                        "handshake operation timed out" in str(e).lower()):
                        sleep(3)
                    elif "bad request" in str(e).lower() and not unsafe:
                        print(fname, url)
                        print(json.dumps(url_par))
                        print_exc()
                        return
                    elif "forbidden" in str(e).lower() and not unsafe:
                        print(fname, url)
                        print(json.dumps(url_par))
                        print_exc()
                        return
                    else:
                        raise e
            self.retry = 0
            return TelegramBot.attributify(json.loads(raw))
        return lambda **kw:func(self,fname.endswith("__UNSAFE"),**kw)
    
    @staticmethod
    def escape(obj):
        if type(obj) == str:
            return obj
        else:
            return json.dumps(obj).encode('utf-8')

    @staticmethod
    def attributify(obj):
        if type(obj)==list:
            return list(map(TelegramBot.attributify,obj))
        elif type(obj)==dict:
            d = obj
            for k in d.keys():
                d[k] = TelegramBot.attributify(d[k])
            return TelegramBot.attribute_dict(d)
        else:
            return obj