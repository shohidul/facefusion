import hashlib
import os
import shutil
import time
from typing import List, Optional, Tuple

import gradio

from facefusion import state_manager, translator
from facefusion.common_helper import get_first
from facefusion.face_store import clear_faces
from facefusion.filesystem import filter_audio_paths, filter_image_paths, has_audio, has_image, remove_file, resolve_file_paths
from facefusion.uis.core import register_ui_component
from facefusion.uis.types import File

SOURCE_FILE_ACCORDION : Optional[gradio.Accordion] = None
SOURCE_FILE : Optional[gradio.File] = None
SOURCE_AUDIO : Optional[gradio.Audio] = None
SOURCE_IMAGE : Optional[gradio.Image] = None
SOURCE_GALLERY : Optional[gradio.Gallery] = None
LIBRARY_GALLERY : Optional[gradio.Gallery] = None
SAVE_LIBRARY_BUTTON : Optional[gradio.Button] = None
CLEAR_LIBRARY_BUTTON : Optional[gradio.Button] = None
REMOVE_LIBRARY_BUTTON : Optional[gradio.Button] = None
REFRESH_LIBRARY_BUTTON : Optional[gradio.Button] = None

SOURCES_DIR = os.path.join(os.getcwd(), 'data', 'sources')
CURRENT_UPLOAD_PATHS : List[str] = []
CURRENT_LIBRARY_PATHS : List[str] = []


def get_library_paths() -> List[str]:
	os.makedirs(SOURCES_DIR, exist_ok = True)
	return filter_image_paths(resolve_file_paths(SOURCES_DIR))


def extract_selected_path(evt : gradio.SelectData, items : List[str]) -> Optional[str]:
	if evt and isinstance(evt.index, int) and 0 <= evt.index < len(items):
		return items[evt.index]
	if evt and isinstance(evt.value, str) and os.path.exists(evt.value):
		return evt.value
	if evt and isinstance(evt.value, dict):
		val = evt.value.get('image', {})
		if isinstance(val, dict) and 'path' in val and os.path.exists(val['path']):
			return val['path']
		if isinstance(val, str) and os.path.exists(val):
			return val
		if 'path' in evt.value and os.path.exists(evt.value['path']):
			return evt.value['path']
	return None


def render() -> None:
	global SOURCE_FILE_ACCORDION
	global SOURCE_FILE
	global SOURCE_AUDIO
	global SOURCE_IMAGE
	global SOURCE_GALLERY
	global LIBRARY_GALLERY
	global SAVE_LIBRARY_BUTTON
	global CLEAR_LIBRARY_BUTTON
	global REMOVE_LIBRARY_BUTTON
	global REFRESH_LIBRARY_BUTTON
	global CURRENT_UPLOAD_PATHS
	global CURRENT_LIBRARY_PATHS

	CURRENT_LIBRARY_PATHS = get_library_paths()
	has_source_audio = has_audio(state_manager.get_item('source_paths'))
	has_source_image = has_image(state_manager.get_item('source_paths'))

	source_file_names = state_manager.get_item('source_paths') if (has_source_audio or has_source_image) else []
	source_audio_path = get_first(filter_audio_paths(source_file_names))
	source_image_path = get_first(filter_image_paths(source_file_names))
	CURRENT_UPLOAD_PATHS = filter_image_paths(source_file_names) if source_file_names else []

	# Collapsible upload box (collapses if library or active face exists)
	with gradio.Accordion('📤 Upload Source File', open = not bool(source_image_path or CURRENT_LIBRARY_PATHS)) as SOURCE_FILE_ACCORDION:
		SOURCE_FILE = gradio.File(
			label = translator.get('uis.source_file'),
			file_count = 'multiple',
			value = source_file_names if source_file_names else None,
			elem_classes = [ 'compact-file-upload' ]
		)

	# Uploaded faces gallery (placed above preview)
	SOURCE_GALLERY = gradio.Gallery(
		value = CURRENT_UPLOAD_PATHS if len(CURRENT_UPLOAD_PATHS) > 0 else None,
		visible = len(CURRENT_UPLOAD_PATHS) > 0,
		columns = 5,
		height = 'auto',
		allow_preview = False,
		preview = False,
		show_label = False,
		show_download_button = False,
		show_fullscreen_button = False,
		object_fit = 'cover',
		type = 'filepath',
		elem_classes = [ 'compact-gallery' ]
	)

	SOURCE_AUDIO = gradio.Audio(
		value = source_audio_path if has_source_audio else None,
		visible = has_source_audio,
		show_label = False
	)
	SOURCE_IMAGE = gradio.Image(
		value = source_image_path if has_source_image else None,
		visible = has_source_image,
		show_label = False
	)

	with gradio.Accordion('📁 Saved Faces Library', open = bool(CURRENT_LIBRARY_PATHS)):
		with gradio.Row(elem_classes = [ 'library-actions-row' ]):
			SAVE_LIBRARY_BUTTON = gradio.Button('💾 Save', size = 'sm', variant = 'secondary', min_width = 0, scale = 1)
			CLEAR_LIBRARY_BUTTON = gradio.Button('❌ Clear', size = 'sm', variant = 'secondary', min_width = 0, scale = 1)
			REMOVE_LIBRARY_BUTTON = gradio.Button('🗑️ Remove', size = 'sm', variant = 'stop', min_width = 0, scale = 1)
			REFRESH_LIBRARY_BUTTON = gradio.Button('🔄 Refresh', size = 'sm', min_width = 0, scale = 1)
		LIBRARY_GALLERY = gradio.Gallery(
			value = CURRENT_LIBRARY_PATHS if CURRENT_LIBRARY_PATHS else None,
			columns = 5,
			height = 'auto',
			allow_preview = False,
			preview = False,
			show_label = False,
			show_download_button = False,
			show_fullscreen_button = False,
			object_fit = 'cover',
			type = 'filepath',
			elem_classes = [ 'compact-gallery' ]
		)

	register_ui_component('source_audio', SOURCE_AUDIO)
	register_ui_component('source_image', SOURCE_IMAGE)
	register_ui_component('source_file_accordion', SOURCE_FILE_ACCORDION)


def listen() -> None:
	SOURCE_FILE.change(update, inputs = SOURCE_FILE, outputs = [ SOURCE_AUDIO, SOURCE_IMAGE, SOURCE_GALLERY, SOURCE_FILE_ACCORDION ])
	SOURCE_GALLERY.select(select_uploaded_face, outputs = [ SOURCE_IMAGE, SOURCE_FILE_ACCORDION, SOURCE_GALLERY, LIBRARY_GALLERY ])
	LIBRARY_GALLERY.select(select_library_face, outputs = [ SOURCE_IMAGE, SOURCE_FILE_ACCORDION, SOURCE_GALLERY, LIBRARY_GALLERY ])
	SAVE_LIBRARY_BUTTON.click(save_to_library, outputs = [ LIBRARY_GALLERY ])
	CLEAR_LIBRARY_BUTTON.click(clear_face_preview, outputs = [ SOURCE_IMAGE, SOURCE_FILE_ACCORDION, SOURCE_GALLERY, LIBRARY_GALLERY ])
	REMOVE_LIBRARY_BUTTON.click(remove_from_library, outputs = [ LIBRARY_GALLERY, SOURCE_IMAGE ])
	REFRESH_LIBRARY_BUTTON.click(refresh_library, outputs = [ LIBRARY_GALLERY ])


def update(files : List[File]) -> Tuple[gradio.Audio, gradio.Image, gradio.Gallery, gradio.Accordion]:
	global CURRENT_UPLOAD_PATHS
	clear_faces()
	file_names = [ file.name for file in files ] if files else None
	has_source_audio = has_audio(file_names)
	has_source_image = has_image(file_names)
	image_paths = filter_image_paths(file_names) if file_names else []
	CURRENT_UPLOAD_PATHS = image_paths

	if has_source_audio or has_source_image:
		source_audio_path = get_first(filter_audio_paths(file_names))
		source_image_path = get_first(image_paths)
		state_manager.set_item('source_paths', [ source_image_path ] if source_image_path else file_names)
		gallery_update = gradio.Gallery(value = image_paths if len(image_paths) > 0 else None, visible = len(image_paths) > 0)
		return gradio.Audio(value = source_audio_path, visible = has_source_audio), gradio.Image(value = source_image_path, visible = has_source_image), gallery_update, gradio.Accordion(open = False)

	state_manager.clear_item('source_paths')
	return gradio.Audio(value = None, visible = False), gradio.Image(value = None, visible = False), gradio.Gallery(value = None, visible = False), gradio.Accordion()


def clear_face_preview() -> Tuple[gradio.Image, gradio.Accordion, gradio.Gallery, gradio.Gallery]:
	clear_faces()
	state_manager.clear_item('source_paths')
	return gradio.Image(value = None, visible = False), gradio.Accordion(open = True), gradio.Gallery(selected_index = None), gradio.Gallery(selected_index = None)


def select_uploaded_face(evt : gradio.SelectData) -> Tuple[gradio.Image, gradio.Accordion, gradio.Gallery, gradio.Gallery]:
	global CURRENT_UPLOAD_PATHS
	clear_faces()
	try:
		from facefusion.uis.components.preview import clear_hold_preview_frame
		clear_hold_preview_frame()
	except Exception:
		pass
	selected_path = extract_selected_path(evt, CURRENT_UPLOAD_PATHS)
	if selected_path and os.path.exists(selected_path):
		state_manager.set_item('source_paths', [ selected_path ])
		return gradio.Image(value = selected_path, visible = True), gradio.Accordion(open = False), gradio.Gallery(selected_index = None), gradio.Gallery(selected_index = None)
	return gradio.Image(), gradio.Accordion(), gradio.Gallery(selected_index = None), gradio.Gallery(selected_index = None)


def select_library_face(evt : gradio.SelectData) -> Tuple[gradio.Image, gradio.Accordion, gradio.Gallery, gradio.Gallery]:
	global CURRENT_LIBRARY_PATHS
	clear_faces()
	try:
		from facefusion.uis.components.preview import clear_hold_preview_frame
		clear_hold_preview_frame()
	except Exception:
		pass
	selected_path = extract_selected_path(evt, CURRENT_LIBRARY_PATHS)
	if selected_path and os.path.exists(selected_path):
		state_manager.set_item('source_paths', [ selected_path ])
		return gradio.Image(value = selected_path, visible = True), gradio.Accordion(open = False), gradio.Gallery(selected_index = None), gradio.Gallery(selected_index = None)
	return gradio.Image(), gradio.Accordion(), gradio.Gallery(selected_index = None), gradio.Gallery(selected_index = None)


def remove_from_library() -> Tuple[gradio.Gallery, gradio.Image]:
	global CURRENT_LIBRARY_PATHS
	source_paths = state_manager.get_item('source_paths')
	if source_paths:
		first_path = get_first(filter_image_paths(source_paths))
		if first_path and os.path.exists(first_path) and os.path.abspath(first_path).startswith(os.path.abspath(SOURCES_DIR)):
			remove_file(first_path)
			clear_faces()
	CURRENT_LIBRARY_PATHS = get_library_paths()
	if CURRENT_LIBRARY_PATHS:
		new_first = CURRENT_LIBRARY_PATHS[0]
		state_manager.set_item('source_paths', [ new_first ])
		return gradio.Gallery(value = CURRENT_LIBRARY_PATHS), gradio.Image(value = new_first, visible = True)
	state_manager.clear_item('source_paths')
	return gradio.Gallery(value = None), gradio.Image(value = None, visible = False)


def get_file_hash(file_path : str) -> Optional[str]:
	if file_path and os.path.isfile(file_path):
		hasher = hashlib.sha256()
		with open(file_path, 'rb') as f:
			for chunk in iter(lambda: f.read(65536), b''):
				hasher.update(chunk)
		return hasher.hexdigest()
	return None


def save_to_library() -> gradio.Gallery:
	global CURRENT_LIBRARY_PATHS
	source_paths = state_manager.get_item('source_paths')
	if source_paths:
		first_path = get_first(filter_image_paths(source_paths))
		if first_path and os.path.exists(first_path):
			CURRENT_LIBRARY_PATHS = get_library_paths()
			if os.path.abspath(first_path).startswith(os.path.abspath(SOURCES_DIR)):
				gradio.Info('Image is already in the saved library.', duration = 2)
				return gradio.Gallery(value = CURRENT_LIBRARY_PATHS)
			new_hash = get_file_hash(first_path)
			if new_hash:
				for existing_path in CURRENT_LIBRARY_PATHS:
					if get_file_hash(existing_path) == new_hash:
						gradio.Info('Duplicate image already exists in library.', duration = 2)
						return gradio.Gallery(value = CURRENT_LIBRARY_PATHS)
			ext = os.path.splitext(first_path)[1] or '.png'
			dst = os.path.join(SOURCES_DIR, f"face_{int(time.time())}{ext}")
			shutil.copy2(first_path, dst)
			gradio.Info('Face successfully saved to library.', duration = 2)
	CURRENT_LIBRARY_PATHS = get_library_paths()
	return gradio.Gallery(value = CURRENT_LIBRARY_PATHS)


def refresh_library() -> gradio.Gallery:
	global CURRENT_LIBRARY_PATHS
	CURRENT_LIBRARY_PATHS = get_library_paths()
	return gradio.Gallery(value = CURRENT_LIBRARY_PATHS)
