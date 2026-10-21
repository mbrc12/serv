#include <Python.h>

#include <limits.h>
#include <mach-o/dyld.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int parent_directory(char *path) {
    char *slash = strrchr(path, '/');
    if (slash == NULL) {
        return -1;
    }
    if (slash == path) {
        slash[1] = '\0';
    } else {
        *slash = '\0';
    }
    return 0;
}

static int set_bundle_environment(const char *executable) {
    char macos_dir[PATH_MAX];
    char contents_dir[PATH_MAX];
    char resources_dir[PATH_MAX];
    char python_home[PATH_MAX];
    char python_executable[PATH_MAX];
    char python_path[PATH_MAX];

    if (snprintf(macos_dir, sizeof(macos_dir), "%s", executable) >= (int)sizeof(macos_dir)
            || parent_directory(macos_dir) != 0
            || snprintf(contents_dir, sizeof(contents_dir), "%s", macos_dir) >= (int)sizeof(contents_dir)
            || parent_directory(contents_dir) != 0
            || snprintf(resources_dir, sizeof(resources_dir), "%s/Resources", contents_dir) >= (int)sizeof(resources_dir)) {
        fprintf(stderr, "serv: app bundle path is too long\n");
        return -1;
    }

    char resolved_resources[PATH_MAX];
    if (realpath(resources_dir, resolved_resources) == NULL) {
        perror("serv: cannot find app resources");
        return -1;
    }
    if (snprintf(python_home, sizeof(python_home), "%s/python", resolved_resources) >= (int)sizeof(python_home)
            || snprintf(python_executable, sizeof(python_executable), "%s/bin/python3", python_home) >= (int)sizeof(python_executable)
            || snprintf(python_path, sizeof(python_path), "%s/pysrc", resolved_resources) >= (int)sizeof(python_path)) {
        fprintf(stderr, "serv: app bundle path is too long\n");
        return -1;
    }

    if (setenv("PYTHONHOME", python_home, 1) != 0
            || setenv("PYTHONPATH", python_path, 1) != 0
            || setenv("PYTHONDONTWRITEBYTECODE", "1", 1) != 0
            || setenv("SERV_APP_LAUNCHER", executable, 1) != 0) {
        perror("serv: cannot set app environment");
        return -1;
    }
    return 0;
}

int main(int argc, char **argv) {
    char raw_executable[PATH_MAX];
    uint32_t path_size = (uint32_t)sizeof(raw_executable);
    if (_NSGetExecutablePath(raw_executable, &path_size) != 0) {
        fprintf(stderr, "serv: app executable path is too long\n");
        return 1;
    }

    char executable[PATH_MAX];
    if (realpath(raw_executable, executable) == NULL) {
        perror("serv: cannot resolve app executable");
        return 1;
    }
    if (set_bundle_environment(executable) != 0) {
        return 1;
    }

    char python_executable[PATH_MAX];
    char resources_dir[PATH_MAX];
    char contents_dir[PATH_MAX];
    char macos_dir[PATH_MAX];
    snprintf(macos_dir, sizeof(macos_dir), "%s", executable);
    parent_directory(macos_dir);
    snprintf(contents_dir, sizeof(contents_dir), "%s", macos_dir);
    parent_directory(contents_dir);
    snprintf(resources_dir, sizeof(resources_dir), "%s/Resources", contents_dir);
    char resolved_resources[PATH_MAX];
    if (realpath(resources_dir, resolved_resources) == NULL
            || snprintf(python_executable, sizeof(python_executable), "%s/python/bin/python3", resolved_resources) >= (int)sizeof(python_executable)) {
        perror("serv: cannot locate bundled Python");
        return 1;
    }

    char **python_argv = calloc((size_t)argc + 3, sizeof(*python_argv));
    if (python_argv == NULL) {
        perror("serv: cannot allocate Python arguments");
        return 1;
    }
    python_argv[0] = python_executable;
    python_argv[1] = "-m";
    python_argv[2] = "serv";
    for (int index = 1; index < argc; index++) {
        python_argv[index + 2] = argv[index];
    }

    int result = Py_BytesMain(argc + 2, python_argv);
    free(python_argv);
    return result;
}
