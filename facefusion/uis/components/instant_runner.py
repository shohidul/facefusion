import os
from time import sleep
from typing import List, Optional, Tuple

import gradio

from facefusion import process_manager, state_manager, translator
from facefusion.args import collect_step_args
from facefusion.core import process_step
from facefusion.filesystem import get_file_extension, is_directory, is_image, is_video
from facefusion.jobs import job_helper, job_manager, job_runner, job_store
from facefusion.temp_helper import clear_temp_directory
from facefusion.types import Args, UiWorkflow
from facefusion.uis.core import get_ui_component
from facefusion.uis.ui_helper import suggest_output_path

INSTANT_RUNNER_WRAPPER : Optional[gradio.Row] = None
INSTANT_RUNNER_START_BUTTON : Optional[gradio.Button] = None
INSTANT_RUNNER_STOP_BUTTON : Optional[gradio.Button] = None
INSTANT_RUNNER_CLEAR_BUTTON : Optional[gradio.Button] = None


def render() -> None:
	global INSTANT_RUNNER_WRAPPER
	global INSTANT_RUNNER_START_BUTTON
	global INSTANT_RUNNER_STOP_BUTTON
	global INSTANT_RUNNER_CLEAR_BUTTON

	if job_manager.init_jobs(state_manager.get_item('jobs_path')):
		is_instant_runner = state_manager.get_item('ui_workflow') == 'instant_runner'

		with gradio.Row(visible = is_instant_runner) as INSTANT_RUNNER_WRAPPER:
			INSTANT_RUNNER_START_BUTTON = gradio.Button(
				value = translator.get('uis.start_button'),
				variant = 'primary',
				size = 'sm'
			)
			INSTANT_RUNNER_STOP_BUTTON = gradio.Button(
				value = translator.get('uis.stop_button'),
				variant = 'primary',
				size = 'sm',
				visible = False
			)
			INSTANT_RUNNER_CLEAR_BUTTON = gradio.Button(
				value = translator.get('uis.clear_button'),
				size = 'sm'
			)


def listen() -> None:
	output_image = get_ui_component('output_image')
	output_video = get_ui_component('output_video')
	ui_workflow_dropdown = get_ui_component('ui_workflow_dropdown')

	if output_image and output_video:
		INSTANT_RUNNER_START_BUTTON.click(start, outputs = [ INSTANT_RUNNER_START_BUTTON, INSTANT_RUNNER_STOP_BUTTON ])
		INSTANT_RUNNER_START_BUTTON.click(run, outputs = [ INSTANT_RUNNER_START_BUTTON, INSTANT_RUNNER_STOP_BUTTON, output_image, output_video ])
		INSTANT_RUNNER_STOP_BUTTON.click(stop, outputs = [ INSTANT_RUNNER_START_BUTTON, INSTANT_RUNNER_STOP_BUTTON, output_image, output_video ])
		INSTANT_RUNNER_CLEAR_BUTTON.click(clear, outputs = [ output_image, output_video ])
	if ui_workflow_dropdown:
		ui_workflow_dropdown.change(remote_update, inputs = ui_workflow_dropdown, outputs = INSTANT_RUNNER_WRAPPER)


def remote_update(ui_workflow : UiWorkflow) -> gradio.Row:
	is_instant_runner = ui_workflow == 'instant_runner'

	return gradio.Row(visible = is_instant_runner)


def start() -> Tuple[gradio.Button, gradio.Button]:
	while not process_manager.is_processing():
		sleep(0.5)
	return gradio.Button(visible = False), gradio.Button(visible = True)


def run() -> Tuple[gradio.Button, gradio.Button, gradio.Image, gradio.Video]:
	step_args = collect_step_args()
	output_path = step_args.get('output_path')

	target_uploads : List[str] = []
	try:
		from facefusion.uis.components.target import get_target_uploads
		target_uploads = [ t for t in get_target_uploads() if os.path.exists(t) ]
	except Exception:
		pass

	is_batch = len(target_uploads) > 1

	if is_batch:
		output_directory = output_path if (output_path and is_directory(output_path)) else (os.path.dirname(output_path) if output_path else None)
		if not output_directory or not os.path.exists(output_directory):
			output_directory = state_manager.get_item('output_path')
			if not output_directory or not is_directory(output_directory):
				output_directory = os.getcwd()

		last_output_path = None
		if job_manager.init_jobs(state_manager.get_item('jobs_path')):
			job_id = job_helper.suggest_job_id('ui')

			for key in job_store.get_job_keys():
				state_manager.sync_item(key) #type:ignore[arg-type]

			if job_manager.create_job(job_id):
				for idx, t_path in enumerate(target_uploads):
					target_step_args = step_args.copy()
					target_step_args['target_path'] = t_path
					base_name, _ = os.path.splitext(os.path.basename(t_path))
					ext = get_file_extension(t_path) or ('.mp4' if is_video(t_path) else '.png')
					dest_file = os.path.join(output_directory, f"{base_name}{ext}")
					if os.path.exists(dest_file):
						dest_file = os.path.join(output_directory, f"{base_name}_{idx + 1}{ext}")
					target_step_args['output_path'] = dest_file
					last_output_path = dest_file
					job_manager.add_step(job_id, target_step_args)

				if job_manager.submit_job(job_id):
					job_runner.run_job(job_id, process_step)

		state_manager.set_item('output_path', output_path)
		if last_output_path and is_image(last_output_path):
			return gradio.Button(visible = True), gradio.Button(visible = False), gradio.Image(value = last_output_path, visible = True, elem_classes = [ 'output-image' ]), gradio.Video(value = None, visible = False)
		if last_output_path and is_video(last_output_path):
			return gradio.Button(visible = True), gradio.Button(visible = False), gradio.Image(value = None, visible = False), gradio.Video(value = last_output_path, visible = True, elem_classes = [ 'output-video' ])
		return gradio.Button(visible = True), gradio.Button(visible = False), gradio.Image(value = None), gradio.Video(value = None)

	if is_directory(step_args.get('output_path')):
		step_args['output_path'] = suggest_output_path(step_args.get('output_path'), state_manager.get_item('target_path'))
	if job_manager.init_jobs(state_manager.get_item('jobs_path')):
		create_and_run_job(step_args)
		state_manager.set_item('output_path', output_path)
	if is_image(step_args.get('output_path')):
		return gradio.Button(visible = True), gradio.Button(visible = False), gradio.Image(value = step_args.get('output_path'), visible = True, elem_classes = [ 'output-image' ]), gradio.Video(value = None, visible = False)
	if is_video(step_args.get('output_path')):
		return gradio.Button(visible = True), gradio.Button(visible = False), gradio.Image(value = None, visible = False), gradio.Video(value = step_args.get('output_path'), visible = True, elem_classes = [ 'output-video' ])
	return gradio.Button(visible = True), gradio.Button(visible = False), gradio.Image(value = None), gradio.Video(value = None)


def create_and_run_job(step_args : Args) -> bool:
	job_id = job_helper.suggest_job_id('ui')

	for key in job_store.get_job_keys():
		state_manager.sync_item(key) #type:ignore[arg-type]

	return job_manager.create_job(job_id) and job_manager.add_step(job_id, step_args) and job_manager.submit_job(job_id) and job_runner.run_job(job_id, process_step)


def stop() -> Tuple[gradio.Button, gradio.Button, gradio.Image, gradio.Video]:
	process_manager.stop()
	return gradio.Button(visible = True), gradio.Button(visible = False), gradio.Image(value = None), gradio.Video(value = None)


def clear() -> Tuple[gradio.Image, gradio.Video]:
	while process_manager.is_processing():
		sleep(0.5)
	if state_manager.get_item('target_path'):
		clear_temp_directory(state_manager.get_item('target_path'))
	return gradio.Image(value = None), gradio.Video(value = None)
