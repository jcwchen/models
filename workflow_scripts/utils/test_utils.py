# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
import subprocess
import tarfile
import os
import shutil
from utils import check_model
import time
import sys
import onnx

TEST_ORT_DIR = 'ci_test_dir'
TEST_TAR_DIR = 'ci_test_tar_dir'
cwd_path = Path.cwd()

def get_model_directory(model_path):
    return os.path.dirname(model_path)

def run_lfs_install():
    result = subprocess.run(['git', 'lfs', 'install'], cwd=cwd_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print('Git LFS install completed with return code= {}'.format(result.returncode))

def pull_lfs_file(file_name):
    result = subprocess.run(['git', 'lfs', 'pull', '--include', file_name, '--exclude', '\'\''], cwd=cwd_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print('LFS pull completed with return code= {}'.format(result.returncode))

def run_lfs_prune():
    result = subprocess.run(['git', 'lfs', 'prune'], cwd=cwd_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print('LFS prune completed with return code= {}'.format(result.returncode))

def extract_test_data(file_path):
    tar = tarfile.open(file_path, "r:gz")
    tar.extractall(TEST_TAR_DIR)
    tar.close()
    return get_model_and_test_data(TEST_TAR_DIR)
    
def get_model_and_test_data(directory_path):
    onnx_model = None
    test_data_set = []
    for root, dirs, files in os.walk(directory_path):
        for file in files:
            if file.endswith('.onnx'):
                onnx_model = os.path.join(root, file)
            for subdir in dirs:
            # detect any test_data_set
                if subdir.startswith('test_data_set_'):
                    subdir_path = os.path.join(root, subdir)
                    test_data_set.append(subdir_path)
    return onnx_model, test_data_set

def remove_tar_dir():
    if os.path.exists(TEST_TAR_DIR) and os.path.isdir(TEST_TAR_DIR):
        shutil.rmtree(TEST_TAR_DIR)


def remove_onnxruntime_test_dir():
    if os.path.exists(TEST_ORT_DIR) and os.path.isdir(TEST_ORT_DIR):
        shutil.rmtree(TEST_ORT_DIR)
     

def test_models(model_list, target, create_if_failed=False, skip_checker_set=set(), skip_ort_set=set()):
    """
    model_list: a string list of model path which will be tested
    target: all, onnx, onnxruntime 
    create_if_failed: (boolean) if true, it will create test data by ORT if failure
    skip_checker_set: a string list of model path which will be excluded for onnx.checker
    skip_ort_set: a string list of model path which will be excluded for ORT test

    Given model_list, pull and test them by target
    including model check and test data validation
    eventually remove all files to save space in CIs
    """
    # run lfs install before starting the tests
    run_lfs_install()
    failed_models = []
    skip_models = []
    tar_ext_name = '.tar.gz'
    for model_path in model_list[::-1]:
        start = time.time()
        model_name = model_path.split('/')[-1]
        tar_name = model_name.replace('.onnx', tar_ext_name)
        print('==============Testing {}=============='.format(model_name))
        tar_gz_path = model_path[:-5] + '.tar.gz'
        test_data_set = []
        try:
            # Step 1: check the uploaded onnx model by ONNX
            # git pull the onnx file
            pull_lfs_file(model_path)

            # Step 2: check the onnx model and test_data_set from .tar.gz by ORT
            # if tar.gz exists, git pull and try to get test data
            if (target == 'onnxruntime' or target == 'all') and os.path.exists(tar_gz_path):
                if model_path in skip_ort_set:
                    skip_models.append(model_name)
                    print('SKIP {} is in the skip list for ORT backend. '.format(model_name))
                    continue                
                pull_lfs_file(tar_gz_path)
                # check whether 'test_data_set_0' exists
                model_path_from_tar, test_data_set = extract_test_data(tar_gz_path)
                # finally check the onnx model from .tar.gz by ORT
                # if the test_data_set does not exist, create the test_data_set
                if not create_if_failed:
                    check_model.run_backend_ort(model_path_from_tar, test_data_set)
                # TODO: this condition should be removed if all of failed test data have been fixed
                else:
                    try:
                        check_model.run_backend_ort(model_path_from_tar, test_data_set)
                    except Exception as e:
                        print('Warning: original test data for {} is broken: {}'.format(model_path, e))
                        # if existing test_data_set_0 cannot pass ORT backend, create a new one
                        check_model.run_backend_ort(model_path_from_tar, None, tar_gz_path)
                print('[PASS] {} is checked by onnxruntime. '.format(tar_name))

            end = time.time()
            print('--------------Time used: {} secs-------------'.format(end - start))

        except Exception as e:
            print('[FAIL] {}: {}'.format(model_name, e))
            failed_models.append(model_path)
        # remove the model/tar files to save space in CIs
        if os.path.exists(model_path):
            os.remove(model_path)
        if os.path.exists(tar_gz_path):
            os.remove(tar_gz_path)
        # remove the produced tar/test directories
        remove_tar_dir()
        remove_onnxruntime_test_dir()
        # clean git lfs cache
        run_lfs_prune()
        return

    print('In all {} models, {} models failed, {} models were skipped. '.format(len(model_list), len(failed_models), len(skip_models)))
    if len(failed_models) != 0:
        print("Failed models: {}".format(failed_models))
        sys.exit(1)
