bl_info = {
    "name": "Westwood3D Tools",
    "author": "Huw Pascoe",
    "version": (1, 0),
    "blender": (2, 80, 0),
    "location": "Import, Export, Material Panel",
    "description": "Enables content authoring for C&C Renegade",
    "warning": "This is a preview and should not be used for projects",
    "wiki_url": "",
    "tracker_url": "",
    "category": "Import-Export"
}

# Module reload
if "bpy" in locals():
    import imp
    imp.reload(w3d_material)
    imp.reload(w3d_struct)
    imp.reload(w3d_aggregate)
    imp.reload(w3d_util)
    imp.reload(w3d_import)
    imp.reload(w3d_export)
else:
    from . import w3d_material, w3d_struct, w3d_aggregate, w3d_util, w3d_import, w3d_export

import bpy

classes = (
    w3d_import.ImportWestwood3D,
    w3d_export.ExportWestwood3D,
    w3d_material.Westwood3DMaterialPassEdit,
    w3d_material.Westwood3DMaterialPass,
    w3d_material.Westwood3DMaterial,
)

def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

    bpy.types.Material.westwood3d = bpy.props.PointerProperty(type=w3d_material.Westwood3DMaterial)
    if hasattr(bpy.types, 'TOPBAR_MT_file_import'):
        # Blender 2.8+
        bpy.types.TOPBAR_MT_file_import.append(w3d_import.menu_func_import)
        bpy.types.TOPBAR_MT_file_export.append(w3d_export.menu_func_export)
    else:
        bpy.types.INFO_MT_file_import.append(w3d_import.menu_func_import)
        bpy.types.INFO_MT_file_export.append(w3d_export.menu_func_export)

def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)

    if hasattr(bpy.types, 'TOPBAR_MT_file_import'):
        # Blender 2.8+
        bpy.types.TOPBAR_MT_file_import.remove(w3d_import.menu_func_import)
        bpy.types.TOPBAR_MT_file_export.remove(w3d_export.menu_func_export)
    else:
        bpy.types.INFO_MT_file_import.remove(w3d_import.menu_func_import)
        bpy.types.INFO_MT_file_export.remove(w3d_export.menu_func_export)

    del bpy.types.Material.westwood3d

if __name__ == "__main__":
    register()
