import os
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import gradio

from facefusion import state_manager, translator
from facefusion.filesystem import is_image, is_video
from facefusion.uis.core import get_ui_components, register_ui_component
from facefusion.vision import detect_video_resolution

OUTPUT_PATH_TEXTBOX : Optional[gradio.Textbox] = None
OUTPUT_IMAGE : Optional[gradio.Image] = None
OUTPUT_VIDEO : Optional[gradio.Video] = None


def render() -> None:
	global OUTPUT_PATH_TEXTBOX
	global OUTPUT_IMAGE
	global OUTPUT_VIDEO

	if not state_manager.get_item('output_path'):
		output_directory = os.path.join(os.getcwd(), 'output')
		os.makedirs(output_directory, exist_ok = True)
		state_manager.set_item('output_path', output_directory)
	OUTPUT_PATH_TEXTBOX = gradio.Textbox(
		label = translator.get('uis.output_path_textbox'),
		value = state_manager.get_item('output_path'),
		max_lines = 1
	)

	target_path = state_manager.get_item('target_path')
	video_classes = [ 'output-video' ]
	if is_video(target_path):
		resolution = detect_video_resolution(target_path)
		if resolution and resolution[1] > resolution[0]:
			video_classes.append('is-portrait')
		else:
			video_classes.append('is-landscape')
	else:
		video_classes.append('is-landscape')

	OUTPUT_IMAGE = gradio.Image(
		label = translator.get('uis.output_image_or_video'),
		visible = is_image(target_path),
		elem_classes = [ 'output-image' ]
	)
	OUTPUT_VIDEO = gradio.Video(
		label = translator.get('uis.output_image_or_video'),
		visible = is_video(target_path) or not is_image(target_path),
		elem_classes = video_classes
	)


def listen() -> None:
	OUTPUT_PATH_TEXTBOX.change(update_output_path, inputs = OUTPUT_PATH_TEXTBOX)
	register_ui_component('output_image', OUTPUT_IMAGE)
	register_ui_component('output_video', OUTPUT_VIDEO)

	for ui_component in get_ui_components([ 'target_image', 'target_video' ]):
		for method in [ 'change', 'clear' ]:
			getattr(ui_component, method)(remote_update, outputs = [ OUTPUT_IMAGE, OUTPUT_VIDEO ])


def remote_update() -> Tuple[gradio.Image, gradio.Video]:
	target_path = state_manager.get_item('target_path')
	if is_image(target_path):
		return gradio.Image(visible = True), gradio.Video(visible = False)
	if is_video(target_path):
		video_classes = [ 'output-video' ]
		resolution = detect_video_resolution(target_path)
		if resolution and resolution[1] > resolution[0]:
			video_classes.append('is-portrait')
		else:
			video_classes.append('is-landscape')
		return gradio.Image(visible = False), gradio.Video(visible = True, elem_classes = video_classes)
	return gradio.Image(visible = False), gradio.Video(visible = True, elem_classes = [ 'output-video', 'is-landscape' ])


def update_output_path(output_path : str) -> None:
	state_manager.set_item('output_path', output_path)
