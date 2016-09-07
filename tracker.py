#!/usr/bin/env python
"""
based on: pgoapi - Pokemon Go API
Copyright (c) 2016 tjado <https://github.com/tejado>

Author: TC    <reddit.com/u/Tr4sHCr4fT>
Version: 0.0.1-pre_alpha
"""
import tweepy
import json, argparse

from time import strftime, localtime, sleep
from datetime import datetime, timedelta
from threading import Thread

from ext import *
from pgoapi.exceptions import NotLoggedInException

log = logging.getLogger(__name__)

def init_config():
    logging.basicConfig(level=logging.INFO, format='[%(levelname)5s] %(asctime)s %(message)s')
    parser = argparse.ArgumentParser()
    config_file = "config.json"

    load = {}
    if os.path.isfile(config_file):
        with open(config_file) as data:
            load.update(json.load(data))

    parser.add_argument("-a", "--auth_service", help="Auth Service ('ptc' or 'google')", default="ptc")
    parser.add_argument("-u", "--username", help="Username")
    parser.add_argument("-p", "--password", help="Password")
    parser.add_argument("-l", "--location", help="Location")    
    parser.add_argument("-r", "--layers", help="Hex layers", default=5, type=int)
    parser.add_argument("-t", "--rhtime", help="max cycle time (minutes)", default=15, type=int)
    parser.add_argument("-d", "--debug", help="Debug Mode", action='store_true', default=0)    
    config = parser.parse_args()

    for key in config.__dict__:
        if key in load and config.__dict__[key] == None:
            config.__dict__[key] = load[key]

    if config.debug:
        logging.getLogger("requests").setLevel(logging.DEBUG)
        logging.getLogger("pgoapi").setLevel(logging.DEBUG)
        logging.getLogger("rpc_api").setLevel(logging.DEBUG)
    else:
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("pgoapi").setLevel(logging.WARNING)
        logging.getLogger("rpc_api").setLevel(logging.WARNING)

    if config.auth_service not in ['ptc', 'google']:
        log.error("Invalid Auth service specified! ('ptc' or 'google')")
        return None

    return config

def main():
    
    config = init_config()
    if not config:
        return
    
    tapi = twit_init()
    lastscan = datetime.now()

    Ptargets,Pfound,Pactive,covers = [],[],[],[]
    
    log.info("Log'in...")
    api = api_init(config)

    watch =  get_pokelist('watch.txt')
    pokes = get_pokenames('pokes.txt')
    
    geolocator = GoogleV3()
    prog = re.compile("^(\-?\d+\.\d+)?,\s*(\-?\d+\.\d+?)$")
    res = prog.match(config.location)
    if res:
        olat, olng, alt = float(res.group(1)), float(res.group(2)), 0
    else:

        loc = geolocator.geocode(config.location, timeout=10)
        if loc:
            log.info("Location for '%s' found: %s", config.location, loc.address)
            log.info('Coordinates (lat/long/alt) for location: %s %s %s', loc.latitude, loc.longitude, loc.altitude)
            olat, olng, alt = loc.latitude, loc.longitude, loc.altitude; del loc
        else:
            return None

    log.info('Generating Hexgrid...')
    grid = hex_spiral(olat, olng, 200, config.layers)
    
    while True:
        
        m = 1
        covers = []
        returntime = datetime.now() + timedelta(minutes=config.rhtime)
        
        for pos in grid:
            
            if datetime.now() > returntime: break
                        
            plat,plng = pos[0],pos[1]
                    
            cell_ids = get_cell_ids(cover_circle(plat, plng, 210, 15))

            while datetime.now() < (lastscan + timedelta(seconds=10)): time.sleep(0.5)
            
            log.info('Scan location %d of %d' % (m,len(grid))); m+=1
            
            response_dict = None
            while response_dict is None:
                timestamps = [0,] * len(cell_ids)
                api.set_position(plat, plng, alt)
                try: response_dict = api.get_map_objects(latitude=plat, longitude=plng, since_timestamp_ms = timestamps, cell_id = cell_ids)
                except NotLoggedInException: api = None; api = api_init(config); time.sleep(10)
                
            lastscan = datetime.now()

            Ctargets = []
            for map_cell in response_dict['responses']['GET_MAP_OBJECTS']['map_cells']:
                if 'catchable_pokemons' in map_cell:
                    for poke in map_cell['catchable_pokemons']:
                        if poke['pokemon_id'] in watch and poke['encounter_id'] not in Pfound:
                            if [poke['encounter_id'],map_cell['s2_cell_id']] in Ptargets:
                                Ptargets.remove([poke['encounter_id'],map_cell['s2_cell_id']])
                            Pfound.append(poke['encounter_id']); Pactive.append(poke)
                            log.info('{} at {}, {}!'.format(pokes[poke['pokemon_id']],poke['latitude'],poke['longitude']))

            for map_cell in response_dict['responses']['GET_MAP_OBJECTS']['map_cells']:
                if 'nearby_pokemons' in map_cell:
                    for poke in map_cell['nearby_pokemons']:
                        if poke['pokemon_id'] not in watch:
                            log.info('{} nearby (ignored)'.format(pokes[poke['pokemon_id']], map_cell['s2_cell_id'])) # this will give you multiple messages for the same pokemon, should probably remove or use an ignore list
                        elif poke['encounter_id'] not in Pfound and [poke['encounter_id'],map_cell['s2_cell_id']] not in Ptargets:
                            Ptargets.append([poke['encounter_id'],map_cell['s2_cell_id']])
                            log.info('{} nearby (locked on!)'.format(pokes[poke['pokemon_id']],map_cell['s2_cell_id']))
                    del Ctargets[:]
                    for Ptarget in Ptargets:
                        if Ptarget[1] not in Ctargets:
                            Ctargets.append(Ptarget[1])

            if len(Ptargets) > 0:
                
                subgrid = hex_spiral(plat, plng, 70, 2)
                subgrid.pop(0) # already scanned in main thread
                
                tempsubgrid = []
                for tmp in subgrid:              
                    q = 0
                    for Ctarget in Ctargets:
                        q += circle_in_cell(CellId(Ctarget), tmp[0], tmp[1], 70, 12)    
                    if q > 0: tempsubgrid.append([tmp,q])
                
                tempsubgrid.sort(key=lambda q:q[1], reverse=True)
                
                subgrid = []
                for tmp in tempsubgrid:
                    subgrid.append(tmp[0])

                s=0
                for spos in subgrid:
                    if len(Ctargets) == 0: break

                    slat,slng = spos[0],spos[1]
                    covers.append([spos[0],spos[1]])
                    
                    cell_ids = get_cell_ids(cover_circle(slat, slng, 75, 15))
                    s += 1
                    log.info('Looking closer for %d pokes, step %d (max %d)' % (len(Ptargets),s,len(subgrid)))

                    response_dict = None
                    while response_dict is None:
                        time.sleep(10)
                        timestamps = [0,] * len(cell_ids)
                        api.set_position(slat, slng, alt)
                        try: response_dict = api.get_map_objects(latitude=slat, longitude=slng, since_timestamp_ms = timestamps, cell_id = cell_ids)
                        except NotLoggedInException: api = None; api = api_init(config)

                    for map_cell in response_dict['responses']['GET_MAP_OBJECTS']['map_cells']:
                        if 'catchable_pokemons' in map_cell:
                            for poke in map_cell['catchable_pokemons']:
                                if poke['pokemon_id'] in watch and poke['encounter_id'] not in Pfound:
                                    if [poke['encounter_id'],map_cell['s2_cell_id']] in Ptargets:
                                        Ptargets.remove([poke['encounter_id'],map_cell['s2_cell_id']])
                                    Pfound.append(poke['encounter_id']); Pactive.append(poke)
                                    log.info('{} at {}, {}!'.format(pokes[poke['pokemon_id']],poke['latitude'],poke['longitude']))
                            del Ctargets[:]
                            for Ptarget in Ptargets:
                                if Ptarget[1] not in Ctargets:
                                    Ctargets.append(Ptarget[1])


# Tweeter
            for p in Pactive:
                
                tmploc = geolocator.reverse((p['latitude'], p['longitude']),exactly_one=True)
                loc = tmploc.address.strip().split(',')
                
                if p['expiration_timestamp_ms'] > 0:
                    t = strftime('%H:%M:%S', time.localtime(int(p['expiration_timestamp_ms']/1000)))
                    tweet = '%s near %s until %s!' %  (pokes[p['pokemon_id']],loc[0],t)
                else:
                    t = strftime('%H:%M:%S', time.localtime((time.time()+900)))
                    tweet = '%s near %s until at least %s!' %  (pokes[p['pokemon_id']],loc[0],t)

                status = tapi.update_status(status=tweet, lat=p['latitude'], long=p['longitude'])
###
        log.info('Back to Start.')

    log.info('Aborted or Error.')


def twit_init():
    # Fill in the values noted in previous step here
    cfg = { 
    "consumer_key"        : "VALUE",
    "consumer_secret"     : "VALUE",
    "access_token"        : "VALUE",
    "access_token_secret" : "VALUE" 
    }
    
    auth = tweepy.OAuthHandler(cfg['consumer_key'], cfg['consumer_secret'])
    auth.set_access_token(cfg['access_token'], cfg['access_token_secret'])
    return tweepy.API(auth)
  
if __name__ == '__main__':
    main()