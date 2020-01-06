import bpy
import bmesh
import mathutils
import os
from typing import cast

from . import w3d_struct, w3d_aggregate, w3d_util

def make_mats(materials):
    for mdata in materials:
        pdata = mdata['mpass']
        
        mat = bpy.data.materials.new('Material')
        mdata['BlenderMaterial'] = mat

        # Setup material
        mat.preview_render_type = 'CUBE'
        mat.use_backface_culling = True
        mat.blend_method = 'HASHED'
        mat.shadow_method = 'HASHED'
        
        w3d = mat.westwood3d
        
        # basic info
        w3d.surface_type = str(mdata['surface'])
        w3d.sort_level = mdata['sort_level']
        
        # add passes
        w3d.mpass_count = len(pdata)
        
        name = ''
        for p in range(len(pdata)):
            mpass = w3d.mpass[p]

            mpass.name = pdata[p]['vertex_material']['name']
            if name != '' and mpass.name != '':
                name += '-' # Add a dash to separate the names

            name += mpass.name
            
            vm = pdata[p]['vertex_material']['info']
            mpass.ambient = vm.Ambient
            mpass.diffuse = vm.Diffuse
            mpass.specular = vm.Specular
            mpass.emissive = vm.Emissive
            mpass.shininess = vm.Shininess
            mpass.opacity = vm.Opacity
            mpass.translucency = vm.Translucency
            mpass.mapping0 = str(vm.Mapping0)
            mpass.mapping1 = str(vm.Mapping1)
            
            sh = pdata[p]['shader']
            mpass.srcblend = str(sh['SrcBlend'])
            mpass.destblend = str(sh['DestBlend'])
            mpass.depthmask = sh['DepthMask']
            mpass.alphatest = sh['AlphaTest']
            
            s = 0
            for stage in pdata[p]['stages']:
                t = bpy.data.textures.new(stage['name'], type='IMAGE')
                t.image = bpy.data.images[stage['name']] if stage['name'] in bpy.data.images else None
                
                if s == 0:
                    mpass.stage0 = t.name
                else:
                    mpass.stage1 = t.name

                s += 1

            if s > 1:
                print('More than 2 stages detected (' + str(s) + ')')
                
        # set name
        if name != '':
            mat.name = name

        # Position the nodes for formatting and readability
        curXPos = 0.0
        gapWidth = 80
        
        # Setup node graph
        mat.use_nodes = True
        tree = mat.node_tree
        for n in tree.nodes:
            tree.nodes.remove(n)

        # Create basic node material
        nodetec = tree.nodes.new('ShaderNodeTexCoord')
        curXPos += nodetec.width + gapWidth

        nodeprin = tree.nodes.new('ShaderNodeBsdfPrincipled')
        nodeout = tree.nodes.new('ShaderNodeOutputMaterial')

        # Reset some default values for the principled node
        nodeprin.inputs[5].default_value = 0.0 # Specular
        nodeprin.inputs[7].default_value = 0.0 # Roughness
        nodeprin.inputs[11].default_value = 0.0 # Screen Tint
        nodeprin.inputs[13].default_value = 0.0 # Clearcoat Roughness
        
        if len(w3d.mpass) > 1:
            nodemix = tree.nodes.new('ShaderNodeMixRGB')

            # Grab the vertex color. This is used for mixing.
            nodecol = tree.nodes.new('ShaderNodeVertexColor')
            nodecol.location = [nodetec.location[0], nodetec.location[1] - nodetec.height - gapWidth]

            tree.links.new(nodecol.outputs[0], nodemix.inputs[0])
            tree.links.new(nodemix.outputs[0], nodeprin.inputs[0])
            r = 1

            curXInc = 0.0
            curYPos = 0.0
            for mpass in w3d.mpass:
                if mpass.stage0 in bpy.data.textures:
                    nodetex = tree.nodes.new('ShaderNodeTexImage')
                    nodetex.image = bpy.data.textures[mpass.stage0].image
                    nodetex.location = [curXPos, curYPos]
                    curXInc = max(curXInc, nodetex.width + gapWidth)
                    curYPos += nodetex.height + gapWidth

                    tree.links.new(nodetec.outputs[2], nodetex.inputs[0])
                    tree.links.new(nodetex.outputs[0], nodemix.inputs[r])
                else:
                    nodeval = tree.nodes.new('ShaderNodeValue')
                    nodeval.location = [curXPos, curYPos]
                    curXInc = max(curXInc, nodeval.width + gapWidth)
                    curYPos += nodeval.height + gapWidth

                    nodeval.outputs[0].default_value = 1.0
                    tree.links.new(nodeval.outputs[0], nodemix.inputs[r])

                # Silently ignore more than 2 passes :|
                r += 1
                if r > 2:
                    break
            
            # Increment the X position.
            curXPos += curXInc

            # Reposition the mix node last
            nodemix.location = [curXPos, 0.0]
            curXPos += nodemix.width + gapWidth
        else:
            for mpass in w3d.mpass:
                # Some materials have nothing as stage0
                if mpass.stage0 in bpy.data.textures:
                    nodetex = tree.nodes.new('ShaderNodeTexImage')
                    nodetex.image = bpy.data.textures[mpass.stage0].image
                    nodetex.location = [curXPos, 0.0]
                    curXPos += nodetex.width + gapWidth

                    tree.links.new(nodetec.outputs[2], nodetex.inputs[0])
                    tree.links.new(nodetex.outputs[0], nodeprin.inputs[0])

                    # Link up TexImage transparency to principled alpha.
                    # Only if alphatest is enabled, or blending indicates alpha enabled.
                    if mpass.alphatest or (mpass.srcblend == "2" and mpass.destblend == "5"):
                        tree.links.new(nodetex.outputs[1], nodeprin.inputs[18])

                    break

        # Diffuse
        nodeprin.location = [curXPos, 0.0]
        curXPos += nodeprin.width + gapWidth
        tree.links.new(nodeprin.outputs[0], nodeout.inputs[0])

        # Put the output node last
        nodeout.location = [curXPos, 0.0]
        curXPos += nodeout.width + gapWidth

def deform_mesh(mesh, mdata, pivots):
    inf = mdata.get('vertex_influences')
    if inf is None:
        return
    inf = inf.influences
    
    bm = bmesh.new()
    bm.from_mesh(mesh)
    for v in bm.verts:
        v.co = pivots[inf[v.index]]['blender_object'].matrix_world @ v.co
    bm.normal_update()
    bm.to_mesh(mesh)


def make_shapes(root, collection):
    shapes = []
    shapes += root.find('box')
    shapes += root.find('sphere')
    shapes += root.find('ring')

    for s in shapes:
        ob = bpy.data.objects.new(s.Name, None)
        ob.location = s.Center
        ob.scale = s.Extent

        # add the shape to the collection
        collection.objects.link(ob)

        if s.type() == 'ring':
            ob.empty_display_type = 'CIRCLE'
        elif s.type() == 'sphere':
            ob.empty_display_type = 'SPHERE'
        else:  # box
            ob.empty_display_type = 'CUBE'

        # for pivot access
        s.blender_object = ob


def make_meshes(root: w3d_struct.node, collection):
    meshes = root.find('mesh')
    for m in meshes:
        info = m.get('mesh_header3')
        fullname = info.ContainerName + '.' + info.MeshName

        verts = cast(w3d_struct.node_vertices, m.get('vertices')).vertices
        faces = cast(w3d_struct.node_triangles, m.get('triangles')).triangles

        tex = m.findRec('texture_name')
        mpass = m.findRec('material_pass')

        tids = m.getRec('texture_ids')
        if tids != None:
            tids = tids.ids

        # create mesh
        me = bpy.data.meshes.new(fullname)

        for p in range(len(mpass)):
            uvs = mpass[p].findRec('stage_texcoords')
            for uv in range(len(uvs)):
                me.uv_layers.new(name='pass' + str(p + 1) + '.' + str(uv))

        bm = bmesh.new()
        bm.from_mesh(me)

        for v in verts:
            bm.verts.new(v)

        # Refresh the lookup table.
        if hasattr(bm.verts, "ensure_lookup_table"): 
            bm.verts.ensure_lookup_table()

        for f in faces:
            try:
                bm.faces.new([bm.verts[i] for i in f['Vindex']]).material_index = f['Mindex']
            except:
                print("duplicate faces encountered on: " + fullname)

        if hasattr(bm.faces, "ensure_lookup_table"):
            bm.faces.ensure_lookup_table()

        if hasattr(bm.edges, "ensure_lookup_table"):
            bm.edges.ensure_lookup_table()

        # vertex color information
        for p in range(len(mpass)):
            dcg = mpass[p].get('dcg')
            if dcg is not None:
                alpha = False
                for c in dcg.dcg:
                    if c[3] < 255:
                        alpha = True
                        break

                layer = bm.loops.layers.color.new('pass' + str(p + 1))
                for v in range(len(bm.verts)):
                    for loop in bm.verts[v].link_loops:
                        col = dcg.dcg[v]
                        if alpha:
                            loop[layer].x = col[3] / 255
                            loop[layer].y = col[3] / 255
                            loop[layer].z = col[3] / 255
                        else:
                            loop[layer].x = col[0] / 255
                            loop[layer].y = col[1] / 255
                            loop[layer].z = col[2] / 255

        # Transfer UVs
        uvs = m.findRec('stage_texcoords')
        for uvi in range(len(uvs)):
            layer = bm.loops.layers.uv[uvi]
            for v in range(len(bm.verts)):
                for loop in bm.verts[v].link_loops:
                    loop[layer].uv = uvs[uvi].texcoords[v]

        # Remove double vertices
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)

        bm.normal_update()
        bm.to_mesh(me)
        bm.free()

        # attach to object, place in scene
        ob = bpy.data.objects.new(fullname, me)
        collection.objects.link(ob)

        user_text = cast(w3d_struct.node_mesh_user_text, m.get('mesh_user_text'))
        if user_text:
            ob["note"] = user_text.text

        # select the objct
        ob.select_set(True)

        # ob.layers[0] = True
        # move hidden objects to second layer
        if info.Attributes & 0x00001000:
            # move vis objects way over there
            if info.Attributes & 0x00000040:
                ob.show_instancer_for_render = False
                ob.show_instancer_for_viewport = False
            else:
                ob.show_instancer_for_render = False
                ob.show_instancer_for_viewport = False

        # materials
        for mat in m.Materials:
            ob.data.materials.append(mat['BlenderMaterial'])

        # assign textures to uv map
        if tids != None and len(tids) > 0 and len(tex) > 0:
            for uvlay in me.uv_layers:
                i = 0
                for foo in uvlay.data:
                    try:
                        foo.image = bpy.data.images[tex[tids[i]].name]
                    except:
                        pass
                    if i < len(tids) - 1:
                        i += 1

        # for pivot access
        m.blender_object = ob


def make_lights(root, collection):
    lightscapes = root.find('lightscape')
    for ls in lightscapes:
        # Add a new blender object for our lightscape.
        ls_ob = bpy.data.objects.new('Lightscape', None)
        collection.objects.link(ls_ob)
        ls_ob.empty_display_type = 'CUBE'

        ls_lts = ls.find('lightscape_light')
        for ls_lt in ls_lts:
            l = ls_lt.get('light')
            li = l.get('light_info')
            lt = ls_lt.get('light_transform')

            power_mult = 1

            attr = li.Attributes
            type = 'NONE'
            name = 'None'
            if (attr & 0xFF) == 0x00000001:
                type = 'POINT'
                name = 'Point'
                power_mult = 100
            elif (attr & 0xFF) == 0x00000002:
                type = 'SUN'
                name = 'Directional'
                power_mult = 1
            elif (attr & 0xFF) == 0x00000003:
                type = 'SPOT'
                name = 'Spot'
                power_mult = 100

            # Create new lamp datablock
            light_data = bpy.data.lights.new(name=name, type=type)

            # Create new object with our lamp datablock
            light_object = bpy.data.objects.new(name=name, object_data=light_data)
            light_object.parent = ls_ob

            # Link lamp object to the scene so it'll appear in this scene
            collection.objects.link(light_object)

            mat = mathutils.Matrix([
                [-lt.Transform[0][0], -lt.Transform[0][1], -lt.Transform[0][2], lt.Transform[0][3]],
                [-lt.Transform[1][0], -lt.Transform[1][1], -lt.Transform[1][2], lt.Transform[1][3]],
                [-lt.Transform[2][0], -lt.Transform[2][1], -lt.Transform[2][2], lt.Transform[2][3]],
                [0, 0, 0, 1]
            ])
            light_object.matrix_world = mat

            # Set the color and intensity
            light_data.color = [
                li.Diffuse[0] / 255.0,
                li.Diffuse[1] / 255.0,
                li.Diffuse[2] / 255.0,
            ]

            light_data.energy = li.Intensity * power_mult


def load_images(root: w3d_struct.node, paths):
    # get every image
    filenames = root.findRec('texture_name')

    for fn in filenames:
        # Don't add duplicates.
        if bpy.data.images.find(fn.name) != -1:
            #print('duplicate image:  ' + fn.name)
            continue
        elif bpy.data.images.find(os.path.splitext(fn.name)[0] + '.dds') != -1:
            # Set the proper extension
            fn.name = os.path.splitext(fn.name)[0] + '.dds'

            #print('duplicate image:  ' + fn.name)
            continue

        img = None
        for path in paths:
            try:
                img = bpy.data.images.load(os.path.join(path, fn.name))
            except:
                # if it failed, try again with .dds
                try:
                    ddsname = os.path.splitext(fn.name)[0] + '.dds'
                    img = bpy.data.images.load(os.path.join(path, ddsname))
                    fn.name = ddsname
                except:
                    pass

            # If image loaded, break
            if img != None:
                break

        if img == None:
            print('image not loaded: ' + fn.name)
        else:
            print('image loaded:     ' + fn.name)

def shift_layer(ob, n):
    for i in range(len(ob.layers)):
        if ob.layers[i]:
            ob.layers[i + n] = True
            ob.layers[i] = False
            break
    
def make_pivots(p, collection, parent=None):
    subobj = []

    # get sub objects
    for data, lod in p['obj']:
        obj = data.blender_object
        subobj.append(obj)

        # LOD is -1 for aggregates.
        if lod == -1:
            for i in range(p['lodcount']):
                #obj.layers[i] = True
                pass
        else:
            #shift_layer(obj, lod)
            pass

    # proxy objects
    for name in p['prx']:
        ob = bpy.data.objects.new(name, None)
        ob.empty_display_type = 'CUBE'
        ob.show_in_front = True
        
        collection.objects.link(ob)
        #for i in range(p['lodcount']):
        #    ob.layers[i] = True
        subobj.append(ob)

    # create node
    if len(subobj) == 1:
        ob = subobj[0]
    else:
        ob = bpy.data.objects.new(p['name'], None)
        collection.objects.link(ob)
        for sub in subobj:
            sub.parent = ob

    # transformations and stuff
    ob.parent = parent
    ob.location += mathutils.Vector(p['translation'])
    ob.rotation_mode = 'QUATERNION'
    r = p['rotation']
    ob.rotation_quaternion = (r[3], r[0], r[1], r[2])
    ob.rotation_mode = 'XYZ'

    # recursive
    for c in p['children']:
        make_pivots(c, collection, ob)

    p['blender_object'] = ob

    # deform all meshes to match bones
    for data, lod in p['obj']:
        if data.type() == 'mesh':
            if data.get('vertex_influences') is not None:
                deform_mesh(data.blender_object.data, data, p['index'])


def make_bones(ob_tree):
    view_layer = bpy.context.view_layer

    name = ob_tree.name
    ob_tree.name = 'temp'
    arm = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, arm)
    view_layer.active_layer_collection.collection.objects.link(ob)

    bpy.ops.object.mode_set(mode='EDIT')
    make_b(ob_tree, arm)
    bpy.ops.object.mode_set(mode='OBJECT')


def make_b(ob, arm, parent=None):
    bone = arm.edit_bones.new(ob.name)

    if ob.location.length > 0:
        # Leaf nodes don't have tails so invent one
        bone.tail = (ob.location.length * 0.5, 0, 0)
    else:
        # X-Up axis for bones apparently
        bone.tail = (0.1, 0, 0)

    # Seems to work
    bone.transform(ob.matrix_world)
    if bone.vector.y >= 0:
        bone.roll = -bone.roll

    # can have connected or loose bones
    if parent:
        if len(ob.parent.children) == 1 and (parent.head - bone.head).length > 0.001:
            parent.tail = bone.head
        else:
            bone.use_connect = False
        bone.parent = parent

    for c in ob.children:
        make_b(c, arm, bone)


def make_anim(anim):
    # TODO: w3d animations have multiple channels, channels are applied to individual pivot points
    # However, blender doesn't allow multiple objects to share a single action without sharing the movements as well.
    # So we have to create actions for each pivot point

    for channel in anim['channels']:
        pivot = channel['pivot']
        bobj = pivot['blender_object']
        bobj.rotation_mode = 'QUATERNION'

        action = None
        actName = anim['name'] + '.' + pivot['name']
        if bpy.data.actions.find(actName) == -1:
            action = bpy.data.actions.new(name=actName)
        else:
            # Hijack the existing action, clear its data.
            action = bpy.data.actions.get(actName)
            for c in action.fcurves:
                action.fcurves.remove(c)

        if bobj.animation_data == None:
            bobj.animation_data_create()
            bobj.animation_data.action = action

        datatype = ''
        idx = -1
        if channel['type'] == 'X':
            datatype = 'location'
            idx = 0
        elif channel['type'] == 'Y':
            datatype = 'location'
            idx = 1
        elif channel['type'] == 'Z':
            datatype = 'location'
            idx = 2
        elif channel['type'] == 'XR':
            datatype = 'rotation_euler'
            idx = 0
        elif channel['type'] == 'YR':
            datatype = 'rotation_euler'
            idx = 1
        elif channel['type'] == 'ZR':
            datatype = 'rotation_euler'
            idx = 2
        elif channel['type'] == 'Q':
            datatype = 'rotation_quaternion'
            idx = -1

        firstFrame = channel['firstframe']
        lastFrame = channel['lastframe']

        # Channel data stuff is an offset from the object's original position.
        # Not quaternion
        if channel['type'] != 'Q':
            fcu = action.fcurves.new(datatype, index=idx)

            initialLoc = bobj.location[idx]

            curFrame = firstFrame
            for vec in channel['data']:
                fcu.keyframe_points.insert(curFrame, initialLoc + vec[0])

                curFrame += 1
        elif channel['type'] == 'Q':
            # Quaternions are special. 4 vector components are included in the data instead of just 1
            # Also blender is backwards and defines quaternions as w x y z, w3d x y z w
            fcus = []
            for i in range(0, 4):
                fcus.append(action.fcurves.new(data_path=datatype, index=i))

            initialQuat = mathutils.Quaternion(bobj.rotation_quaternion)

            curFrame = firstFrame
            for vec in channel['data']:
                quat = mathutils.Quaternion((vec[3], vec[0], vec[1], vec[2]))
                rotQuat = initialQuat @ quat

                fcus[0].keyframe_points.insert(curFrame, rotQuat.w)
                fcus[1].keyframe_points.insert(curFrame, rotQuat.x)
                fcus[2].keyframe_points.insert(curFrame, rotQuat.y)
                fcus[3].keyframe_points.insert(curFrame, rotQuat.z)

                curFrame += 1

def load_scene(root: w3d_struct.node, collection: bpy.types.Collection, paths, ignore_lightmap):
    load_images(root, paths)

    # Gather up all materials
    materials = w3d_util.mat_reduce(root, ignore_lightmap)

    # Collect the renderables, pivots, and animations.
    robj = w3d_util.collect_render_objects(root)
    pivots = w3d_util.make_pivots(root, robj)
    anims = w3d_util.make_anims(root, pivots)

    make_mats(materials)
    make_meshes(root, collection)
    make_shapes(root, collection)
    make_lights(root, collection)

    for p in pivots.values():
        make_pivots(p, collection)

    for a in anims.values():
        make_anim(a)

    # load aggregates
    for ag in root.find('aggregate'):
        info = ag.get('aggregate_info')
        index = pivots[info.BaseModelName]['index']
        for s in info.Subobjects:
            bone = s['BoneName']
            for i in index:
                if i['agname'] == bone:
                    break
            pivots[s['SubobjectName']]['blender_object'].parent = i['blender_object']


# ImportHelper is a helper class, defines filename and
# invoke() function which calls the file selector.
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, BoolProperty, CollectionProperty
from bpy.types import Operator, OperatorFileListElement


class ImportWestwood3D(Operator, ImportHelper):
    '''This appears in the tooltip of the operator and in the generated docs'''
    bl_idname      = "import.westwood3d"
    bl_label       = "Import Westwood3D"
    bl_description = "Import Westwood 3D geometry"

    # ImportHelper mixin class uses this
    filename_ext = ".w3d"

    filter_glob: StringProperty(
        default="*.w3d;*.wlt",
        options={'HIDDEN'},
    )

    files: CollectionProperty(
        name="W3D files",
        type=OperatorFileListElement,
    )

    directory: StringProperty(subtype='DIR_PATH')

    # List of operator properties, the attributes will be assigned
    # to the class instance from the operator settings before calling.
    ignore_lightmap: BoolProperty(
        name="Don't import lightmaps",
        description="Lightmap data increases material count",
        default=True,
    )

    attempt_proxies: BoolProperty(
        name="Attempt to import proxies as w3d files",
        description="This will attempt to import all proxies as w3d files. Proxy names commonly correspond to w3d files.",
        default=False
    )

    def load_file(self, file):
        # source directories
        current_path = os.path.dirname(file)
        paths = [
            current_path,
            os.path.join(current_path, '../always/'),
            os.path.join(current_path, '../textures/'),
            os.path.join(current_path, 'textures/'),
        ]
        
        # Load data
        try:
            root = w3d_struct.load(file)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        try:
            w3d_aggregate.aggregate(root, paths)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        
        # grab the current layer
        view_layer = bpy.context.view_layer

        # Load the scene.
        load_scene(root, view_layer.active_layer_collection.collection, paths, self.ignore_lightmap)
        return {'FINISHED'}

    def execute(self, context):
        for f in self.files:
            self.load_file(os.path.join(self.directory, f.name))

        return {'FINISHED'}
        
# Only needed if you want to add into a dynamic menu
def menu_func_import(self, context):
    self.layout.operator(ImportWestwood3D.bl_idname, text="Westwood3D (.w3d)")
