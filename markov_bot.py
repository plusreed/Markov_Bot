# Library imports
import gc
import hashlib
import logging
import os
import os.path
import pickle
import random
import requests
import shlex
import sys
from threading import Thread
import time
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

import bot_class
from config import TOKEN, USER_AGENT

SENT = False

groups = {}
          
# Unicode character categories considered    
ALLOWABLE = ["Lc","Ll","Lm","Lo","Lt","Lu","Nd","Nl","No"]
COMMON_T = 0

SPLIT_LINES = False
LAST_USER = {}

# Supported TTS languages
LANGS = ["af","an","bg","bs","ca","cs","cy","da","de","el","en","en-gb","en-sc","en-uk-north","en-uk-rp","en-uk-wmids","en-us","en-wi","eo","es","es-la","et","fa","fa-pin","fi","fr-be","fr-fr","ga","grc","hi","hr","hu","hy","hy-west","id","is","it","jbo","ka","kn","ku","la","lfn","lt","lv","mk","ml","ms","ne","nl","no","pa","pl","pt-br","pt-pt","ro","ru","sk","sq","sr","sv","sw","ta","tr","vi","vi-hue","vi-sgn","zh","zh-yue"]

gcache = []
# how many groups will be cached at most at one time
max_cache_size = 10
# GC is forced every N group unloads
gc_every_unload = 30
gc_counter = gc_every_unload

# obtained when the bot is initialized
MY_USERNAME = ""

# whether to auto-restart?
Restart = False

try:
    from urllib.error import URLError
except ImportError:
    from urllib2 import URLError 

def save(reason):
    print("SAVING ",reason)
    for key in groups:
        save_group(key)
    print("SAVED")
    
bot = bot_class.TelegramBot(TOKEN)
MY_USERNAME = bot.getMe().result.username.lower()

last_msg_id = 0

def addMessage(message, g):
    w = [""] + message.lower().split(" ") + [""]
    for i in range(1,len(w)):
        lw = "".join(filter(lambda x:(unicodedata.category(x) in ALLOWABLE),w[i-1]))
        nw = w[i]
        if len(lw) < 50 and len(nw) < 50:
            if lw not in g.keys():
                g[lw] = []
            g[lw].append(nw)

def limit(s):
    t = " ".join(s.split(" ")[:50])
    return t[:400]

def load_group(chat_id):
    global gcache
    try:
        with open("markov/chat_" + str(chat_id) + ".dat", "rb") as f:
            groups[chat_id] = pickle.load(f)
        gcache.append(chat_id)
    except KeyboardInterrupt as e:
        raise e
    except:
        pass
    check_cache()

def check_cache():
    global gcache
    while len(gcache) > max_cache_size:
        unload_group(gcache[0])

def unload_group(chat_id):
    global gcache, gc_counter
    try:
        with open("markov/chat_" + str(chat_id) + ".dat", "wb") as f:
            pickle.dump(groups[chat_id], f)
            groups[chat_id] = None
            del groups[chat_id]
        gcache.remove(chat_id)
        gc_counter -= 1
        if gc_counter < 1:
            gc_counter = gc_every_unload
            gc.collect()
    except KeyboardInterrupt as e:
        raise e
    except:
        pass

def save_group(chat_id):
    try:
        with open("markov/chat_" + str(chat_id) + ".dat", "wb") as f:
            pickle.dump(groups[chat_id], f)
    except:
        pass
    
def generateMarkovOgg(msg, g):
    # g are the group settings
    # msg is the message data
    # call espeak and opusenc
    os.system("rm markov.ogg 2>nul")    
    os.system("espeak -s" + str(g[2]) + " -v" + g[1] + " " + shlex.quote(limit(msg)) + " --stdout | opusenc - markov.ogg >nul 2>&1")

tried_to = 0
saferes = True
OFF = 0
try:
    def autoreset():
        time.sleep(600)
        while not saferes:
            time.sleep(0.5)
        time.sleep(30)
        save("quitting - backup thread")
        os.execl(sys.executable, sys.executable, *sys.argv)      
    if Restart:
        Thread(target=autoreset, daemon=True).start()
    while True:
        tried_to += 1
        if tried_to >= 1000 and Restart:
            save("quitting")
            os.execl(sys.executable, sys.executable, *sys.argv)
        print("poll " + str(time.time()),end=":")
        saferes = False
        try:
            updates = bot.getUpdates__UNSAFE(offset=OFF, timeout=5).result
        except KeyboardInterrupt as e:
            print("E")
            raise e
        except BaseException as e:
            print("0")
            if str(e).strip().lower() != "timeout":
                print("poll failed: ", e)
            continue     
        print(len(updates), end="")
        print("(" + str(OFF) + ")")
        for update in updates:
            last_msg_id = update.update_id
            OFF = update.update_id + 1
            if not update.has("message"):
                continue
            if update.message == None:
                continue
            chat_id = update.message.chat.id
            chat_type = update.message.chat.type
            if update.message.has("migrate_from_chat_id"):
                nid = update.message.chat.id
                oid = update.message.migrate_from_chat_id
                if oid == nid:
                    continue
                if oid in gcache:
                    unload_group(oid)
                # rename db file
                try:
                    os.rename("markov/chat_" + str(oid) + ".dat", "markov/chat_" + str(nid) + ".dat")
                except: # file does not exist, ignore
                    pass    
                continue
            if update.message.has("text"):
                message = update.message.text
            else:
                message = ""
            replyto = update.message.message_id
            if update.message.has("from"):
                user = update.message["from"].id
            else:
                user = -1
            admbypass = False
            try:
                admbypass = admbypass or update.message.chat.all_members_are_administrators
            except:
                pass

            if chat_id not in gcache:
                load_group(chat_id)

            if chat_id not in groups.keys():
                groups[chat_id] = {}
                gcache.append(chat_id)
                check_cache()
                    
            # g contents
            # [mlimit, tts language, tts speed, markov collecting (pause/resume), ~ maximum words]
            g = groups[chat_id]
            if g == None:   
                groups[chat_id] = {}
                g = {}
            if 0 not in g.keys():
                g[0] = 1
            if 1 not in g.keys():
                g[1] = "en"
            if 2 not in g.keys():
                g[2] = 100
            if 3 not in g.keys():
                g[3] = True
            if 4 not in g.keys():
                g[4] = 10000
                
            curtime = time.time()
            t = str(user) + ":" + str(chat_id)
            
            if len(message) < 1:
                continue
            if message[0] == "/":
                rcmd = message.split(" ")[0].split("@")[0]
                if "@" in message.split(" ")[0]:
                    cmdtarget = message.split(" ")[0].split("@")[1]
                    # if the command is aimed at some other bot
                    if cmdtarget.lower() != MY_USERNAME:
                        continue
                cmd = rcmd.lower()
                if cmd == "/markov":
                    if t in LAST_USER.keys():
                        if (curtime - LAST_USER[t]) < g[0]:
                            continue

                    LAST_USER[t] = curtime
                    COMMON_T += 1
                    if COMMON_T == 8:
                        COMMON_T = 0
                    tries_o = 0
                    if "" in g.keys():
                        while True:
                            tries_o += 1
                            words = []
                            word = ""
                            if random.randint(0,10)<5:
                                word = random.choice(list(filter(lambda x:type(x)==str,g.keys())))
                            else:
                                word = random.choice(g[word])
                            while word != "" and len(words) < min(g[4],10000):
                                words.append(word)
                                word = "".join(filter(lambda x:(unicodedata.category(x) in ALLOWABLE),word)).lower()
                                if word not in g.keys():
                                    word = ""
                                else:
                                    word = random.choice(g[word])
                            msg = " ".join(words)
                            if len(msg) > 0: break
                            if tries_o > 1000: break
                        try:
                            bot.sendMessage(chat_id=chat_id,
                                text=msg)
                        except KeyboardInterrupt as e:
                            raise e
                        except:
                            pass
                    else:
                        try:
                            bot.sendMessage(chat_id=chat_id,
                                text="[Chain is empty]",
                                reply_to_message_id=replyto)
                        except KeyboardInterrupt as e:
                            raise e
                        except:
                            pass
                if cmd == "/mlimit":
                    if t in LAST_USER.keys():
                        if (curtime - LAST_USER[t]) < 1:
                            continue
                    try:
                        st = bot.getChatMember(chat_id=chat_id, user_id=user).result.status
                        if chat_type in ["group","supergroup","channel"] and not admbypass and (st != "administrator" and st != "creator"):
                            continue
                    except KeyboardInterrupt as e:
                        raise e
                    except:
                        pass
                    t = " ".join(message.split(" ")[1:]).strip()
                    if len(t) < 1:
                        bot.sendMessage(chat_id=chat_id,
                                text="[Usage: /mlimit seconds, current limit is {0}]".format(str(g[0])),
                                reply_to_message_id=replyto)
                        continue
                    try:
                        v = int(t)
                    except KeyboardInterrupt as e:
                        raise e
                    except:
                        bot.sendMessage(chat_id=chat_id,
                                text="[Usage: /mlimit seconds, current limit is {0}]".format(str(g[0])),
                                reply_to_message_id=replyto)
                        continue
                    if v <= 0 or v > 100000:
                        bot.sendMessage(chat_id=chat_id,
                                text="[limit must be between 1-100 000 seconds]",
                                reply_to_message_id=replyto)
                        continue
                    #print(t, "=", g[0])
                    bot.sendMessage(chat_id=chat_id,
                            text="[Limit set to {0} seconds]".format(str(v)),
                            reply_to_message_id=replyto)
                    g[0] = v
                if cmd == "/markovttsspeed":
                    if t in LAST_USER.keys():
                        if (curtime - LAST_USER[t]) < 1:
                            continue
                    t = " ".join(message.split(" ")[1:]).strip()
                    if len(t) < 1:
                        bot.sendMessage(chat_id=chat_id,
                                text="[Usage: /markovttsspeed wpm, current wpm is {0}]".format(str(g[2])),
                                reply_to_message_id=replyto)
                        continue
                    try:
                        v = int(t)
                    except KeyboardInterrupt as e:
                        raise e
                    except:
                        bot.sendMessage(chat_id=chat_id,
                                text="[Usage: /markovttsspeed wpm, current wpm is {0}]".format(str(g[2])),
                                reply_to_message_id=replyto)
                        continue
                    if v < 80 or v > 500:
                        bot.sendMessage(chat_id=chat_id,
                                text="[Speed must be between 80-500 wpm]",
                                reply_to_message_id=replyto)
                        continue
                    bot.sendMessage(chat_id=chat_id,
                            text="[Speed set to {0}]".format(str(v)),
                            reply_to_message_id=replyto)
                    g[2] = v
                if cmd == "/markovmaxwords":
                    if t in LAST_USER.keys():
                        if (curtime - LAST_USER[t]) < 1:
                            continue
                    try:
                        st = bot.getChatMember(chat_id=chat_id, user_id=user).result.status
                        if chat_type in ["group","supergroup","channel"] and not admbypass and (st != "administrator" and st != "creator"):
                            continue
                    except KeyboardInterrupt as e:
                        raise e
                    except:
                        pass
                    t = " ".join(message.split(" ")[1:]).strip()
                    if len(t) < 1:
                        bot.sendMessage(chat_id=chat_id,
                                text="[Usage: /markovmaxwords words, current max words is {0}]".format(str(g[4])),
                                reply_to_message_id=replyto)
                        continue
                    try:
                        v = int(t)
                    except KeyboardInterrupt as e:
                        raise e
                    except:
                        bot.sendMessage(chat_id=chat_id,
                                text="[Usage: /markovmaxwords words, current max words is {0}]".format(str(g[4])),
                                reply_to_message_id=replyto)
                        continue
                    if v < 1 or v > 10000:
                        bot.sendMessage(chat_id=chat_id,
                                text="[Limit for words is 1-10000]",
                                reply_to_message_id=replyto)
                        continue
                    g[4] = v
                    save_group(chat_id)
                    bot.sendMessage(chat_id=chat_id,
                        text="[Maximum words set to {0}]".format(str(v)),
                        reply_to_message_id=replyto)                    
                if cmd == "/markovclear":
                    if t in LAST_USER.keys():
                        if (curtime - LAST_USER[t]) < 1:
                            continue
                    try:
                        # do not allow non-admins to clear
                        st = bot.getChatMember(chat_id=chat_id, user_id=user).result.status
                        if chat_type in ["group","supergroup","channel"] and not admbypass and (st != "administrator" and st != "creator"):
                            continue
                    except KeyboardInterrupt as e:
                        raise e
                    except:
                        pass
                    checkhash = hashlib.md5((str(chat_id)+str(user)+str(time.time()//1000)).encode("utf-8")).hexdigest()[:12].upper()
                    what = ""
                    try:
                        what = message.split(" ")[1].upper()
                    except KeyboardInterrupt as e:
                        raise e
                    except:
                        pass
                    if what == checkhash:
                        groups[chat_id] = {}
                        save_group(chat_id)
                        bot.sendMessage(chat_id=chat_id,
                            text="[Messages cleared]",
                            reply_to_message_id=replyto)                    
                    else:
                        bot.sendMessage(chat_id=chat_id,
                            text="[Copy this to confirm]\n/markovclear " + checkhash,
                            reply_to_message_id=replyto)
                if cmd == "/markovpause":
                    if t in LAST_USER.keys():
                        if (curtime - LAST_USER[t]) < 1:
                            continue
                    try:
                        st = bot.getChatMember(chat_id=chat_id, user_id=user).result.status
                        if chat_type in ["group","supergroup","channel"] and not admbypass and (st != "administrator" and st != "creator"):
                            continue
                    except KeyboardInterrupt as e:
                        raise e
                    except:
                        pass
                    g[3] = False
                    save_group(chat_id)
                    bot.sendMessage(chat_id=chat_id,
                        text="[Reading paused]",
                        reply_to_message_id=replyto)                    
                if cmd == "/markovresume":
                    if t in LAST_USER.keys():
                        if (curtime - LAST_USER[t]) < 1:
                            continue
                    try:
                        st = bot.getChatMember(chat_id=chat_id, user_id=user).result.status
                        if chat_type in ["group","supergroup","channel"] and not admbypass and (st != "administrator" and st != "creator"):
                            continue
                    except KeyboardInterrupt as e:
                        raise e
                    except:
                        pass
                    g[3] = True
                    save_group(chat_id)
                    bot.sendMessage(chat_id=chat_id,
                        text="[Reading resumed]",
                        reply_to_message_id=replyto)                    
                if cmd == "/markovtts":
                    if t in LAST_USER.keys():
                        if (curtime - LAST_USER[t]) < max(5,g[0]):
                            continue
                    LAST_USER[t] = curtime
                    COMMON_T += 1
                    if COMMON_T == 8:
                        COMMON_T = 0
                    if "" in g.keys():
                        while True:
                            words = []
                            word = ""
                            if random.randint(0,10)<5:
                                word = random.choice(list(filter(lambda x:type(x)==str,g.keys())))
                            else:
                                word = random.choice(g[word])
                            while word != "" and len(words) < min(g[4],120):
                                words.append(word)
                                word = "".join(filter(lambda x:(unicodedata.category(x) in ALLOWABLE),word)).lower()
                                if word not in g.keys():
                                    word = ""
                                else:
                                    word = random.choice(g[word])
                            msg = " ".join(words)
                            if len(msg) > 0: break
                        try:
                            generateMarkovOgg(msg, g)
                            headers = {'User-Agent': USER_AGENT}
                            files = {"voice": open("markov.ogg","rb")}
                            bot.sendVoice(_urlopen_hook=lambda u:requests.post(u, headers=headers, files=files).text,
                                chat_id=chat_id)
                        except KeyboardInterrupt as e:
                            raise e
                        except BaseException as e:
                            exc_type, exc_value, exc_traceback = sys.exc_info()
                            print("\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback)))
                            bot.sendMessage(chat_id=chat_id,
                                    text="Could not send voice",
                                    reply_to_message_id=replyto)                    
                    else:
                        bot.sendMessage(chat_id=chat_id,
                                text="[Chain is empty]",
                                reply_to_message_id=replyto)
                if cmd == "/markovttslang":
                    if t in LAST_USER.keys():
                        if (curtime - LAST_USER[t]) < 1:
                            continue
                    v = " ".join(message.split(" ")[1:]).strip()
                    if v not in LANGS:
                        bot.sendMessage(chat_id=chat_id,
                                text=("[Unknown language]\n" if len(v) > 0 else "") + ", ".join(LANGS),
                                reply_to_message_id=replyto)
                        continue
                    bot.sendMessage(chat_id=chat_id,
                            text="[Language set]",
                            reply_to_message_id=replyto)
                    g[1] = v
            elif message[0] != "/":
                if g[3]:
                    if SPLIT_LINES:
                        for line in message.split("\n"):
                            addMessage(line, g)
                    else:
                        addMessage(message, g)      
                saferes = True
        time.sleep(0.02)
except KeyboardInterrupt as e:
    save("Quit")
except BaseException as e:
    save("Exception")
    traceback.print_exc()
    