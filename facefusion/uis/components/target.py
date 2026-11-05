import os
import shutil
import time
from typing import Any, List, Optional, Tuple

import gradio

from facefusion import state_manager, translator
from facefusion.common_helper import get_first
from facefusion.face_store import clear_faces
from facefusion.filesystem import is_image, is_video, remove_file, resolve_file_paths
from facefusion.uis.core import register_ui_component
from facefusion.uis.types import ComponentOptions, File

TARGET_FILE_ACCORDION : Optional[gradio.Accordion] = None
TARGET_FILE : Optional[gradio.File] = None
TARGET_IMAGE : Optional[gradio.Image] = None
TARGET_VIDEO : Optional[gradio.Video] = None
TARGET_GALLERY : Optional[gradio.Gallery] = None
TARGET_LIBRARY_GALLERY : Optional[gradio.Gallery] = None
SAVE_TARGET_BUTTON : Optional[gradio.Button] = None
REFRESH_TARGET_BUTTON : Optional[gradio.Button] = None
CLEAR_TARGETS_BUTTON : Optional[gradio.Button] = None

TARGETS_DIR = os.path.join(os.getcwd(), 'data', 'targets')
TARGETS_UPLOAD_DIR = os.path.join(TARGETS_DIR, 'uploads')
CURRENT_TARGET_UPLOADS : List[str] = []
CURRENT_TARGET_LIBRARY : List[str] = []


def get_persisted_target_uploads() -> List[str]:
	os.makedirs(TARGETS_UPLOAD_DIR, exist_ok = True)
	all_paths = resolve_file_paths(TARGETS_UPLOAD_DIR)
	return [ p for p in all_paths if is_image(p) or is_video(p) ]


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
	global REFRESH_TARGET_BUTTON
	global CLEAR_TARGETS_BUTTON
	global CURRENT_TARGET_UPLOADS
	global CURRENT_TARGET_LIBRARY

	CURRENT_TARGET_UPLOADS = get_persisted_target_uploads()
	is_target_image = is_image(state_manager.get_item('target_path'))
	is_target_video = is_video(state_manager.get_item('target_path'))

	# If active target is not set but persisted uploads exist, set first one as active
	if not (is_target_image or is_target_video) and CURRENT_TARGET_UPLOADS:
		first_target = CURRENT_TARGET_UPLOADS[0]
		state_manager.set_item('target_path', first_target)
		is_target_image = is_image(first_target)
		is_target_video = is_video(first_target)

	active_target = state_manager.get_item('target_path')

	# Collapsible upload box (collapses if uploads or library exist)
	with gradio.Accordion('📤 Upload Target Files', open = not bool(CURRENT_TARGET_UPLOADS or active_target)) as TARGET_FILE_ACCORDION:
		TARGET_FILE = gradio.File(
			label = translator.get('uis.target_file'),
			file_count = 'multiple',
			value = CURRENT_TARGET_UPLOADS if CURRENT_TARGET_UPLOADS else None,
			elem_classes = [ 'compact-file-upload' ]
		)

	# Uploaded target gallery (placed above preview)
	with gradio.Row():
		TARGET_GALLERY = gradio.Gallery(
			label = 'Uploaded Targets (Click to Select)',
			value = CURRENT_TARGET_UPLOADS if len(CURRENT_TARGET_UPLOADS) > 1 else None,
			visible = len(CURRENT_TARGET_UPLOADS) > 1,
			columns = 5,
			height = 'auto',
			allow_preview = False,
			preview = False,
			show_download_button = False,
			show_fullscreen_button = False,
			object_fit = 'cover',
			type = 'filepath',
			elem_classes = [ 'compact-gallery' ],
			scale = 4
		)
	with gradio.Row():
		CLEAR_TARGETS_BUTTON = gradio.Button('🗑️ Clear Uploaded Targets', size = 'sm', visible = len(CURRENT_TARGET_UPLOADS) > 0, scale = 1, min_width = 0)

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
			SAVE_TARGET_BUTTON = gradio.Button('💾 Save Active Target', size = 'sm', variant = 'secondary', min_width = 0, scale = 1)
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


def listen() -> None:
	TARGET_FILE.change(update, inputs = TARGET_FILE, outputs = [ TARGET_IMAGE, TARGET_VIDEO, TARGET_GALLERY, TARGET_FILE_ACCORDION, CLEAR_TARGETS_BUTTON ])
	TARGET_GALLERY.select(select_uploaded_target, outputs = [ TARGET_IMAGE, TARGET_VIDEO, TARGET_FILE_ACCORDION ])
	TARGET_LIBRARY_GALLERY.select(select_library_target, outputs = [ TARGET_IMAGE, TARGET_VIDEO, TARGET_FILE_ACCORDION ])
	CLEAR_TARGETS_BUTTON.click(clear_persisted_targets, outputs = [ TARGET_GALLERY, TARGET_FILE, CLEAR_TARGETS_BUTTON ])
	SAVE_TARGET_BUTTON.click(save_to_library, outputs = [ TARGET_LIBRARY_GALLERY ])
	REFRESH_TARGET_BUTTON.click(refresh_library, outputs = [ TARGET_LIBRARY_GALLERY ])


def update(files : List[File]) -> Tuple[gradio.Image, gradio.Video, gradio.Gallery, gradio.Accordion, gradio.Button]:
	global CURRENT_TARGET_UPLOADS
	clear_faces()

	if files:
		for file in files:
			if is_image(file.name) or is_video(file.name):
				base_name = os.path.basename(file.name)
				dst = os.path.join(TARGETS_UPLOAD_DIR, base_name)
				if not os.path.exists(dst):
					shutil.copy2(file.name, dst)

	CURRENT_TARGET_UPLOADS = get_persisted_target_uploads()

	if CURRENT_TARGET_UPLOADS:
		first_file = CURRENT_TARGET_UPLOADS[0]
		gallery_update = gradio.Gallery(value = CURRENT_TARGET_UPLOADS if len(CURRENT_TARGET_UPLOADS) > 1 else None, visible = len(CURRENT_TARGET_UPLOADS) > 1)
		clear_btn_update = gradio.Button(visible = True)

		if is_image(first_file):
			state_manager.set_item('target_path', first_file)
			return gradio.Image(value = first_file, visible = True), gradio.Video(value = None, visible = False), gallery_update, gradio.Accordion(open = False), clear_btn_update

		if is_video(first_file):
			state_manager.set_item('target_path', first_file)
			return gradio.Image(value = None, visible = False), gradio.Video(value = first_file, visible = True), gallery_update, gradio.Accordion(open = False), clear_btn_update

	state_manager.clear_item('target_path')
	return gradio.Image(value = None, visible = False), gradio.Video(value = None, visible = False), gradio.Gallery(value = None, visible = False), gradio.Accordion(), gradio.Button(visible = False)


def select_uploaded_target(evt : gradio.SelectData) -> Tuple[gradio.Image, gradio.Video, gradio.Accordion]:
	global CURRENT_TARGET_UPLOADS
	clear_faces()
	selected_path = extract_selected_path(evt, CURRENT_TARGET_UPLOADS)
	if selected_path and os.path.exists(selected_path):
		state_manager.set_item('target_path', selected_path)
		if is_image(selected_path):
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
			return gradio.Image(value = selected_path, visible = True), gradio.Video(value = None, visible = False), gradio.Accordion(open = False)
		if is_video(selected_path):
			return gradio.Image(value = None, visible = False), gradio.Video(value = selected_path, visible = True), gradio.Accordion(open = False)
	return gradio.Image(), gradio.Video(), gradio.Accordion()


def clear_persisted_targets() -> Tuple[gradio.Gallery, gradio.File, gradio.Button]:
	global CURRENT_TARGET_UPLOADS
	if os.path.exists(TARGETS_UPLOAD_DIR):
		for item in os.listdir(TARGETS_UPLOAD_DIR):
			item_path = os.path.join(TARGETS_UPLOAD_DIR, item)
			if os.path.isfile(item_path) and not item.startswith('.'):
				remove_file(item_path)
	CURRENT_TARGET_UPLOADS = []
	return gradio.Gallery(value = None, visible = False), gradio.File(value = None), gradio.Button(visible = False)


def save_to_library() -> gradio.Gallery:
	global CURRENT_TARGET_LIBRARY
	target_path = state_manager.get_item('target_path')
	if target_path and os.path.exists(target_path):
		ext = os.path.splitext(target_path)[1] or '.png'
		dst = os.path.join(TARGETS_DIR, f"target_{int(time.time())}{ext}")
		shutil.copy2(target_path, dst)
	CURRENT_TARGET_LIBRARY = get_target_library_paths()
	return gradio.Gallery(value = CURRENT_TARGET_LIBRARY)


def refresh_library() -> gradio.Gallery:
	global CURRENT_TARGET_LIBRARY
	CURRENT_TARGET_LIBRARY = get_target_library_paths()
	return gradio.Gallery(value = CURRENT_TARGET_LIBRARY)
