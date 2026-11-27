// SPDX-License-Identifier: GPL-3.0-or-later
#include "common.h"
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#define rec_dup _dup
#define rec_dup2 _dup2
#define rec_fileno _fileno
#define rec_fdopen _fdopen
#else
#define rec_dup dup
#define rec_dup2 dup2
#define rec_fileno fileno
#define rec_fdopen fdopen
#endif

static FILE *frames;
static unsigned int step_number;
static int buttons;
static int dt_ticks;

void recorder_init(void) {
	if (!check_param("--recorder")) return;
	int fd = rec_dup(rec_fileno(stdout));
	if (fd < 0 || rec_dup2(rec_fileno(stderr), rec_fileno(stdout)) < 0) exit(2);
#ifdef _WIN32
	_setmode(fd, _O_BINARY);
	_setmode(rec_fileno(stdin), _O_BINARY);
#endif
	frames = rec_fdopen(fd, "wb");
	if (!frames) exit(2);
}

int recorder_active(void) {
	return frames != NULL;
}

int recorder_period(void) {
	return Kid.sword == sword_2_drawn ? custom->fight_speed : custom->base_speed;
}

void recorder_read_action(void) {
	int mask = fgetc(stdin);
	if (mask == EOF) exit(ferror(stdin) ? 2 : 0);
	if (mask > 31 || (mask & 3) == 3 || (mask & 12) == 12) exit(2);
	buttons = mask;
	dt_ticks = recorder_period();
	++step_number;
}

void recorder_apply_action(void) {
	control_x = (buttons & 1) ? CONTROL_HELD_LEFT : (buttons & 2) ? CONTROL_HELD_RIGHT : CONTROL_RELEASED;
	control_y = (buttons & 4) ? CONTROL_HELD_UP : (buttons & 8) ? CONTROL_HELD_DOWN : CONTROL_RELEASED;
	control_shift = (buttons & 16) ? CONTROL_HELD : CONTROL_RELEASED;
}

void recorder_frame(void) {
	// One post-render observation, including the native HUD, per simulation step.
	static unsigned char rgb[320 * 200 * 3];
	SDL_Surface *surface = onscreen_surface_;
	if (!surface || surface->w != 320 || surface->h != 200 ||
	    SDL_ConvertPixels(320, 200, surface->format->format, surface->pixels,
	                      surface->pitch, SDL_PIXELFORMAT_RGB24, rgb, 320 * 3) < 0) {
		fprintf(stderr, "recorder: RGB capture failed: %s\n", SDL_GetError());
		exit(2);
	}
	const char *end = "playing";
	if (current_level == custom->win_level && drawn_room == custom->win_room) end = "victory";
	else if (next_level != current_level) end = "level_complete";
	else if (hitp_curr == 0 || Kid.alive >= 0) end = "death";
	else if (rem_min == 0 && current_level < 13) end = "time_expired";

	if (fprintf(frames, "POP1 %u %d %d %d %s %d %d %d %d %d %d %d %d\n",
	            step_number, buttons, dt_ticks, recorder_period(), end, current_level, Kid.room,
	            Kid.x, Kid.y, Kid.direction, hitp_curr, Kid.frame, Kid.sword) < 0 ||
	    fwrite(rgb, 1, sizeof(rgb), frames) != sizeof(rgb) || fflush(frames) != 0) exit(2);
	if (strcmp(end, "playing") != 0) exit(0);
}
