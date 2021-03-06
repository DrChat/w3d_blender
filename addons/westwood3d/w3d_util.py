import copy
import struct
from typing import cast, Any, Dict, List

from . import w3d_struct

def collect_render_objects(root):
    robj = {}
    
    for m in root.find('mesh'):
        info = m.get('mesh_header3')
        name = info.ContainerName + '.' + info.MeshName
        robj[name] = m
    for s in root.find('box'):
        robj[s.Name] = s
    for s in root.find('sphere'):
        robj[s.Name] = s
    for s in root.find('ring'):
        robj[s.Name] = s
    
    return robj
    
def make_pivots(root: w3d_struct.node, robj: Dict[str, w3d_struct.node]):
    pivotdict = {}
    
    for hroot in root.find('hlod'):
        info = cast(w3d_struct.node_hlod_header, hroot.get('hlod_header'))
        if info is None:
            continue

        hierarchy = None
        hname = None
        for h in root.find('hierarchy'):
            hh = cast(w3d_struct.node_hierarchy_header, h.get('hierarchy_header'))
            
            hname = hh.Name
            if info.HierarchyName == hname:
                hierarchy = h
                break

        if hierarchy is None:
            continue

        # Compile pivot data into a proper tree
        pivots = []
        for pdata in cast(w3d_struct.node_pivots, hierarchy.get('pivots')).pivots:
            p = {
                'index': pivots, 'name': pdata['Name'], 'agname': pdata['Name'],
                'children': [], 'obj': [], 'prx': [], 'lodcount': info.LodCount,
            }
            
            if pdata['ParentIdx'] != 0xffffffff:
                pivots[pdata['ParentIdx']]['children'].append(p)
            else:
                p['name'] = info.Name
                pivotdict[info.Name] = p
            
            p['translation'] = pdata['Translation']
            p['rotation'] = pdata['Rotation']
            pivots.append(p)
        
        # Assign name-lod tuple to pivots
        lod = info.LodCount
        for hlod in hroot.find('hlod_lod_array'):
            lod -= 1
            for h in hlod.find('hlod_sub_object'):
                if h.Name in robj:
                    pivots[h.BoneIndex]['obj'].append((robj[h.Name], lod))
        
        # aggregates appear in all LOD
        for hlod in hroot.find('hlod_aggregate_array'):
            for h in hlod.find('hlod_sub_object'):
                if h.Name in robj:
                    pivots[h.BoneIndex]['obj'].append((robj[h.Name], -1))
        
        # proxy objects are special
        for hlod in hroot.find('hlod_proxy_array'):
            for h in hlod.find('hlod_sub_object'):
                pivots[h.BoneIndex]['prx'].append(h.Name)
    
    return pivotdict

def make_anims(root: w3d_struct.node, pivots) -> Dict[str, dict]:
    animdict = {}

    for animroot in root.find("animation"):
        if animroot == None:
            continue

        head = cast(w3d_struct.node_animation_header, animroot.get("animation_header"))
        animdict[head.Name] = {
            'hname': head.HierarchyName, 'name': head.Name, 'numframes': head.NumFrames,
            'framerate': head.FrameRate, 'channels': [], 'bitchannels': [],
        }

        bitchannels = animroot.find("bit_channel")

        for bitchan in bitchannels:
            # TODO
            pass

        channels = cast(List[w3d_struct.node_animation_channel], animroot.find("animation_channel"))

        for chan in channels:
            chanout = {
                'firstframe': chan.FirstFrame, 'lastframe': chan.LastFrame, 'data': []
            }

            # What the channel controls
            type = ''
            if chan.Flags == 0:
                type = 'X' # X/Y/Z translation
            elif chan.Flags == 1:
                type = 'Y'
            elif chan.Flags == 2:
                type = 'Z'
            elif chan.Flags == 3:
                type = 'XR' # X/Y/Z rotation
            elif chan.Flags == 4:
                type = 'YR'
            elif chan.Flags == 5:
                type = 'ZR'
            elif chan.Flags == 6:
                type = 'Q' # Quaternion

            chanout['type'] = type
            chanout['vectorlen'] = chan.VectorLen

            # Animation data
            size = ((chan.LastFrame - chan.FirstFrame + 1) * chan.VectorLen) * 4
            if size != len(chan.Data):
                raise ValueError('animation channel has bad data length')

            offset = 0
            while offset < size:
                data = struct.unpack_from(str(chan.VectorLen) + 'f', chan.Data, offset)

                veclist = []
                for i in range(0, chan.VectorLen):
                    veclist.append(data[i])

                chanout['data'].append(veclist)

                offset += struct.calcsize(str(chan.VectorLen) + 'f')

            # Link the pivot
            pivotobj = None
            for pivotn in pivots:
                if pivotobj != None:
                    break

                if pivotn == head.HierarchyName:
                    i = 0
                    for p in pivots[pivotn]['index']:
                        if i == chan.Pivot:
                            pivotobj = p
                            break

                        i += 1

            chanout['pivot'] = pivotobj
            animdict[head.Name]['channels'].append(chanout)

    return animdict
    
def mat_reduce(root: w3d_struct.node, ignore_lightmap: bool) -> list:
    """Runs through all the meshes and generate a list of materials.
    """
    materials = []
    mathash = {}
    
    for mesh in root.find('mesh'):
        meshinfo = cast(w3d_struct.node_mesh_header3, mesh.get('mesh_header3'))
        verts = cast(w3d_struct.node_vertices, mesh.get('vertices')).vertices
        faces = cast(w3d_struct.node_triangles, mesh.get('triangles')).triangles
        mpass = cast(List[w3d_struct.node_material_pass], mesh.findRec('material_pass'))
        texnames = cast(List[w3d_struct.node_texture_name], mesh.findRec('texture_name'))
        vmnames = cast(List[w3d_struct.node_vertex_material_name], mesh.findRec('vertex_material_name'))
        vminfos = cast(List[w3d_struct.node_vertex_material_info], mesh.findRec('vertex_material_info'))
        shaders = cast(w3d_struct.node_shaders, mesh.getRec('shaders'))
        
        fmhash = {}
        mesh.Materials = []
        faceidx = 0
        for face in faces:
            # Gather face information
            finfo = {}
            
            # get surface
            finfo['surface'] = face['Attributes']
            
            finfo['mpass'] = []
            for p in mpass:
                vmids = cast(w3d_struct.node_vertex_material_ids, p.get('vertex_material_ids'))
                shids = cast(w3d_struct.node_shader_ids, p.get('shader_ids'))

                pinfo = { 'stages': [] }
                
                # get vertex material
                ids = vmids.ids
                pinfo['vmid'] = ids[face['Vindex'][0]] if len(ids) > 1 else ids[0]
                
                # remove lightmaps if not wanted
                if ignore_lightmap and vmnames[pinfo['vmid']].name == 'Lightmap':
                    mpass.remove(p)
                    continue
                
                # get shader
                ids = shids.ids
                pinfo['sid'] = ids[faceidx] if len(ids) > 1 else ids[0]
                
                # get textures
                stage = p.get('texture_stage')
                if stage is not None:
                    for tex in stage.findRec('texture_ids'):
                        ids = tex.ids
                        pinfo['stages'].append(ids[faceidx] if len(ids) > 1 else ids[0])
                
                finfo['mpass'].append(pinfo)
            
            faceidx += 1
            
            # Reduce face info to materials
            h = make_hash(finfo)
            if h in fmhash:
                face['Mindex'] = fmhash[h]
                continue
            
            # Material are stored in an array with the mesh
            # and material index is stored with face
            face['Mindex'] = len(mesh.Materials)
            fmhash[h] = len(mesh.Materials)
            
            # Compile material
            mat = { 'mpass': [] }
            mat['surface'] = finfo['surface']
            mat['sort_level'] = meshinfo.SortLevel
            
            for pinfo in finfo['mpass']:
                p = { 'vertex_material': {}, 'stages': [] }
                p['shader'] = shaders.shaders[pinfo['sid']]
                p['vertex_material']['name'] = vmnames[pinfo['vmid']].name
                p['vertex_material']['info'] = vminfos[pinfo['vmid']]
                for id in pinfo['stages']:
                    if id < len(texnames):
                        p['stages'].append({ 'name': texnames[id].name })
                mat['mpass'].append(p)
            
            # Reduce materials to share between meshes
            h = make_hash(mat)
            if h in mathash:
                mat = mathash[h]
            else:
                mathash[h] = mat
                materials.append(mat)
            
            mesh.Materials.append(mat)
    
    return materials
    
# thanks jomido @ stackoverflow!
DictProxyType = type(object.__dict__)

def make_hash(o):

    """
    Makes a hash from a dictionary, list, tuple or set to any level, that 
    contains only other hashable types (including any lists, tuples, sets, and
    dictionaries). In the case where other kinds of objects (like classes) need 
    to be hashed, pass in a collection of object attributes that are pertinent. 
    For example, a class can be hashed in this fashion:

        make_hash([cls.__dict__, cls.__name__])

    A function can be hashed like so:

        make_hash([fn.__dict__, fn.__code__])
    """

    if type(o) == DictProxyType:
        o2 = {}
        for k, v in o.items():
            if not k.startswith("__"):
                o2[k] = v
        o = o2    

    if isinstance(o, set) or isinstance(o, tuple) or isinstance(o, list):
        return tuple([make_hash(e) for e in o])
    elif not isinstance(o, dict):
        return hash(o)

    new_o = copy.deepcopy(o)
    for k, v in new_o.items():
        new_o[k] = make_hash(v)

    return hash(tuple(frozenset(new_o.items())))
