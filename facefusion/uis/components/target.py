import hashlib
import os
import shutil
import time
from typing import Any, List, Optional, Tuple

import gradio

from facefusion import state_manager, translator
from facefusion.common_helper import get_first
from facefusion.face_store import clear_faces
from facefusion.filesystem import is_image, is_video, remove_file, resolve_file_paths, resolve_real_file_path
from facefusion.uis.core import register_ui_component
from facefusion.uis.types import ComponentOptions, File

TARGET_FILE_ACCORDION : Optional[gradio.Accordion] = None
TARGET_FILE : Optional[gradio.File] = None
TARGET_IMAGE : Optional[gradio.Image] = None
TARGET_VIDEO : Optional[gradio.Video] = None
TARGET_GALLERY : Optional[gradio.Gallery] = None
TARGET_LIBRARY_GALLERY : Optional[gradio.Gallery] = None
SAVE_TARGET_BUTTON : Optional[gradio.Button] = None
CLEAR_TARGET_BUTTON : Optional[gradio.Button] = None
REMOVE_TARGET_BUTTON : Optional[gradio.Button] = None
REFRESH_TARGET_BUTTON : Optional[gradio.Button] = None

TARGETS_DIR = os.path.join(os.getcwd(), 'data', 'targets')
CURRENT_TARGET_UPLOADS : List[str] = []
CURRENT_TARGET_LIBRARY : List[str] = []
TARGET_ORIGIN_MAP : dict[str, str] = {}


def get_target_library_paths() -> List[str]:
	os.makedirs(TARGETS_DIR, exist_ok = True)
	all_paths = resolve_file_paths(TARGETS_DIR)
	return [ p for p in all_paths if is_image(p) or is_video(p) ]


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
	global TARGET_FILE_ACCORDION
	global TARGET_FILE
	global TARGET_IMAGE
	global TARGET_VIDEO
	global TARGET_GALLERY
	global TARGET_LIBRARY_GALLERY
	global SAVE_TARGET_BUTTON
	global CLEAR_TARGET_BUTTON
	global REMOVE_TARGET_BUTTON
	global REFRESH_TARGET_BUTTON
	global CURRENT_TARGET_UPLOADS
	global CURRENT_TARGET_LIBRARY

	is_target_image = is_image(state_manager.get_item('target_path'))
	is_target_video = is_video(state_manager.get_item('target_path'))
	active_target = state_manager.get_item('target_path')

	# Collapsible upload box (persists collapsed state)
	with gradio.Accordion('📤 Upload Target Files', open = not bool(active_target)) as TARGET_FILE_ACCORDION:
		TARGET_FILE = gradio.File(
			label = translator.get('uis.target_file'),
			file_count = 'multiple',
			value = [ active_target ] if (is_target_image or is_target_video) else None,
			elem_classes = [ 'compact-file-upload' ]
		)

	target_file_names = [ f.get('path') if isinstance(f, dict) else f for f in TARGET_FILE.value ] if TARGET_FILE.value else []
	CURRENT_TARGET_UPLOADS = target_file_names

	# Uploaded target gallery (placed above preview)
	TARGET_GALLERY = gradio.Gallery(
		value = CURRENT_TARGET_UPLOADS if len(CURRENT_TARGET_UPLOADS) > 0 else None,
		visible = len(CURRENT_TARGET_UPLOADS) > 0,
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

	target_image_options : ComponentOptions =\
	{
		'show_label': False,
		'visible': False
	}
	target_video_options : ComponentOptions =\
	{
		'show_label': False,
		'visible': False
	}
	if is_target_image:
		target_image_options['value'] = active_target
		target_image_options['visible'] = True
	if is_target_video:
		target_video_options['value'] = active_target
		target_video_options['visible'] = True
	TARGET_IMAGE = gradio.Image(**target_image_options)
	TARGET_VIDEO = gradio.Video(**target_video_options)

	# Saved Targets Library
	CURRENT_TARGET_LIBRARY = get_target_library_paths()
	with gradio.Accordion('📁 Saved Targets Library', open = bool(CURRENT_TARGET_LIBRARY)):
		with gradio.Row(elem_classes = [ 'library-actions-row' ]):
			SAVE_TARGET_BUTTON = gradio.Button('💾 Save', size = 'sm', variant = 'secondary', min_width = 0, scale = 1)
			CLEAR_TARGET_BUTTON = gradio.Button('❌ Clear', size = 'sm', variant = 'secondary', min_width = 0, scale = 1)
			REMOVE_TARGET_BUTTON = gradio.Button('🗑️ Remove', size = 'sm', variant = 'stop', min_width = 0, scale = 1)
			REFRESH_TARGET_BUTTON = gradio.Button('🔄 Refresh', size = 'sm', min_width = 0, scale = 1)
		TARGET_LIBRARY_GALLERY = gradio.Gallery(
			value = CURRENT_TARGET_LIBRARY if CURRENT_TARGET_LIBRARY else None,
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

	register_ui_component('target_image', TARGET_IMAGE)
	register_ui_component('target_video', TARGET_VIDEO)
	register_ui_component('target_gallery', TARGET_GALLERY)


def listen() -> None:
	TARGET_FILE.change(update, inputs = TARGET_FILE, outputs = [ TARGET_IMAGE, TARGET_VIDEO, TARGET_GALLERY, TARGET_FILE_ACCORDION ])
	TARGET_GALLERY.select(select_uploaded_target, outputs = [ TARGET_IMAGE, TARGET_VIDEO, TARGET_FILE_ACCORDION ])
	TARGET_LIBRARY_GALLERY.select(select_library_target, outputs = [ TARGET_IMAGE, TARGET_VIDEO, TARGET_FILE_ACCORDION ])
	SAVE_TARGET_BUTTON.click(save_to_library, outputs = [ TARGET_LIBRARY_GALLERY ])
	CLEAR_TARGET_BUTTON.click(clear_target_preview, outputs = [ TARGET_IMAGE, TARGET_VIDEO, TARGET_FILE_ACCORDION ])
	REMOVE_TARGET_BUTTON.click(remove_from_library, outputs = [ TARGET_LIBRARY_GALLERY, TARGET_IMAGE, TARGET_VIDEO ])
	REFRESH_TARGET_BUTTON.click(refresh_library, outputs = [ TARGET_LIBRARY_GALLERY ])


def update(files : List[File]) -> Tuple[gradio.Image, gradio.Video, gradio.Gallery, gradio.Accordion]:
	global CURRENT_TARGET_UPLOADS, TARGET_ORIGIN_MAP
	clear_faces()
	file_names = [ file.name for file in files ] if files else []
	CURRENT_TARGET_UPLOADS = file_names

	if file_names:
		for fn in file_names:
			try:
				real_fn = resolve_real_file_path(fn)
				if real_fn and real_fn != fn:
					TARGET_ORIGIN_MAP[fn] = real_fn
					TARGET_ORIGIN_MAP[os.path.basename(fn)] = real_fn
			except Exception:
				pass

		first_file = file_names[0]
		gallery_update = gradio.Gallery(value = file_names if len(file_names) > 0 else None, visible = len(file_names) > 0)

		if is_image(first_file):
			state_manager.set_item('target_path', first_file)
			try:
				from facefusion.uis.components.preview import register_original_target_frame
				register_original_target_frame(first_file)
			except Exception:
				pass
			return gradio.Image(value = first_file, visible = True), gradio.Video(value = None, visible = False), gallery_update, gradio.Accordion(open = False)

		if is_video(first_file):
			state_manager.set_item('target_path', first_file)
			return gradio.Image(value = None, visible = False), gradio.Video(value = first_file, visible = True), gallery_update, gradio.Accordion(open = False)

	state_manager.clear_item('target_path')
	return gradio.Image(value = None, visible = False), gradio.Video(value = None, visible = False), gradio.Gallery(value = None, visible = False), gradio.Accordion()


def clear_target_preview() -> Tuple[gradio.Image, gradio.Video, gradio.Accordion]:
	clear_faces()
	state_manager.clear_item('target_path')
	return gradio.Image(value = None, visible = False), gradio.Video(value = None, visible = False), gradio.Accordion(open = True)


def select_uploaded_target(evt : gradio.SelectData) -> Tuple[gradio.Image, gradio.Video, gradio.Accordion]:
	global CURRENT_TARGET_UPLOADS
	clear_faces()
	selected_path = extract_selected_path(evt, CURRENT_TARGET_UPLOADS)
	if selected_path and os.path.exists(selected_path):
		state_manager.set_item('target_path', selected_path)
		if is_image(selected_path):
			try:
				from facefusion.uis.components.preview import register_original_target_frame
				register_original_target_frame(selected_path)
			except Exception:
				pass
			return gradio.Image(value = selected_path, visible = True), gradio.Video(value = None, visible = False), gradio.Accordion(open = False)
		if is_video(selected_path):
			return gradio.Image(value = None, visible = False), gradio.Video(value = selected_path, visible = True), gradio.Accordion(open = False)
	return gradio.Image(), gradio.Video(), gradio.Accordion()


def select_library_target(evt : gradio.SelectData) -> Tuple[gradio.Image, gradio.Video, gradio.Accordion]:
	global CURRENT_TARGET_LIBRARY
	clear_faces()
	selected_path = extract_selected_path(evt, CURRENT_TARGET_LIBRARY)
	if selected_path and os.path.exists(selected_path):
		state_manager.set_item('target_path', selected_path)
		if is_image(selected_path):
			try:
				from facefusion.uis.components.preview import register_original_target_frame
				register_original_target_frame(selected_path)
			except Exception:
				pass
			return gradio.Image(value = selected_path, visible = True), gradio.Video(value = None, visible = False), gradio.Accordion(open = False)
		if is_video(selected_path):
			return gradio.Image(value = None, visible = False), gradio.Video(value = selected_path, visible = True), gradio.Accordion(open = False)
	return gradio.Image(), gradio.Video(), gradio.Accordion()


def remove_from_library() -> Tuple[gradio.Gallery, gradio.Image, gradio.Video]:
	global CURRENT_TARGET_LIBRARY
	target_path = state_manager.get_item('target_path')
	if target_path and os.path.exists(target_path) and os.path.abspath(target_path).startswith(os.path.abspath(TARGETS_DIR)):
		remove_file(target_path)
		clear_faces()
	CURRENT_TARGET_LIBRARY = get_target_library_paths()
	if CURRENT_TARGET_LIBRARY:
		new_first = CURRENT_TARGET_LIBRARY[0]
		state_manager.set_item('target_path', new_first)
		if is_image(new_first):
			return gradio.Gallery(value = CURRENT_TARGET_LIBRARY), gradio.Image(value = new_first, visible = True), gradio.Video(value = None, visible = False)
		if is_video(new_first):
			return gradio.Gallery(value = CURRENT_TARGET_LIBRARY), gradio.Image(value = None, visible = False), gradio.Video(value = new_first, visible = True)
	state_manager.clear_item('target_path')
	return gradio.Gallery(value = None), gradio.Image(value = None, visible = False), gradio.Video(value = None, visible = False)


def get_file_hash(file_path : str) -> Optional[str]:
	if file_path and os.path.isfile(file_path):
		hasher = hashlib.sha256()
		with open(file_path, 'rb') as f:
			for chunk in iter(lambda: f.read(65536), b''):
				hasher.update(chunk)
		return hasher.hexdigest()
	return None


def save_to_library() -> gradio.Gallery:
	global CURRENT_TARGET_LIBRARY
	target_path = state_manager.get_item('target_path')
	if target_path and os.path.exists(target_path):
		CURRENT_TARGET_LIBRARY = get_target_library_paths()
		if os.path.abspath(target_path).startswith(os.path.abspath(TARGETS_DIR)):
			gradio.Info('Target is already in the saved library.', duration = 2)
			return gradio.Gallery(value = CURRENT_TARGET_LIBRARY)
		new_hash = get_file_hash(target_path)
		if new_hash:
			for existing_path in CURRENT_TARGET_LIBRARY:
				if get_file_hash(existing_path) == new_hash:
					gradio.Info('Duplicate target already exists in library.', duration = 2)
					return gradio.Gallery(value = CURRENT_TARGET_LIBRARY)
		ext = os.path.splitext(target_path)[1] or '.png'
		dst = os.path.join(TARGETS_DIR, f"target_{int(time.time())}{ext}")
		shutil.copy2(target_path, dst)
		gradio.Info('Target successfully saved to library.', duration = 2)
	CURRENT_TARGET_LIBRARY = get_target_library_paths()
	return gradio.Gallery(value = CURRENT_TARGET_LIBRARY)


def refresh_library() -> gradio.Gallery:
	global CURRENT_TARGET_LIBRARY
	CURRENT_TARGET_LIBRARY = get_target_library_paths()
	return gradio.Gallery(value = CURRENT_TARGET_LIBRARY)
