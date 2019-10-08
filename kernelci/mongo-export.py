#!/usr/bin/env python3
#
# WIP: xfer kernelCI test data from mongodb to BQ
# - assumes local copy of kci mongodb
#
# FIXME
# - handle nested groups with recursion
#
import pymongo
import pprint
from bson.objectid import ObjectId
import datetime
from dateutil.relativedelta import relativedelta
import json

kcidb_export = {
    'version': "1",
}

test_group_db = None
test_case_db = None
tests = {}

def handle_test_group(tg, build, environment, name):
    global test_group_db, test_case_db, tests

    name += tg['name']

    # First handle sub groups
    for sg_id in tg['sub_groups']:
        sg_id = str(sg_id)
        for sg in test_group_db.find({'_id': ObjectId(sg_id)}):
            handle_test_group(sg, build, environment, name + "/")

    # then test_cases
    for tc_id in tg['test_cases']:
        tc_id = str(tc_id)
        tc = test_case_db.find_one({'_id': ObjectId(tc_id)})
        
        tc_name = name + '/' + tc['name']
        print("    T:", tc_name)
        if tc_id in tests:
            print("WARN: test case %s already seen." % tc_id)
            continue
            
        test = {
            'build_origin': "kernelci",
            'build_origin_id': build['origin_id'],

            'environment_origin': "kernelci",
            'environment_origin_id': environment['origin_id'],
            
            'origin': "kernelci",
            'origin_id': tc_id,
            
            'description': tc_name,
            'status': tc['status'],
            
            'misc': {
                key:tg[key] for key in ['lab_name', 'board', 'board_instance', 'boot_log']
            }
        }

        tests[tc_id] = test
    
def main():
    global test_group_db, test_case_db, tests
    
    mongo_client = pymongo.MongoClient()
    db = mongo_client['kernel-ci']

    test_group_db = db['test_group']
    test_case_db = db['test_case']
    build_db = db['build']

    builds = {}
    revisions = {}
    environments = {}
    
    tg_count = 0
    start_date = datetime.datetime.now()
    start_date = start_date - datetime.timedelta(days=45)
    #filter_expr = None
    filter_expr = {'created_on': {'$gte': start_date}}

    #
    # First, iterater over (most) top-level test_groups
    #
    for tg in test_group_db.find(filter_expr):
        if tg['name'] == "lava":
            continue

        # skip non-LAVA labs
        if tg['lab_name'] in ["lab-baylibre-seattle", "lab-bjorn"]:
            continue
        
        # skip plain boot jobs
        if tg['name'] == "boot":
            continue
        
        # skip non top-level test_groups
        if 'parent_id' in tg and tg['parent_id']:
            continue

        created_on = tg['created_on']
        build_id = str(tg['build_id'])
        build_kci = build_db.find_one({'_id': ObjectId(build_id)})
        #pprint.pprint(build_kci)
    
        revision_id = '/'.join([build_kci['job'], build_kci['git_branch'], build_kci['git_describe']])
        print("R:", revision_id)
        if not revision_id in revisions:
            revision = {
                'origin': "kernelci",
                'origin_id': revision_id,
                'git_repository_url': build_kci['git_url'],
                'git_repository_commit_hash': build_kci['git_commit'],
                'misc': {key:build_kci[key] for key in ['git_branch', 'git_describe']},
            }
            revision['misc']['created_on'] = created_on.isoformat(),
            revisions[revision_id] = revision
        
        build_desc = "/".join([build_kci['arch'], build_kci['defconfig_full'], build_kci['compiler'] + '-' + build_kci['compiler_version']])
        print("  B:", build_desc)
        if not build_id in builds:
            build = {
                'origin': "kernelci",
                'origin_id': build_id,
                'description': build_desc,
                'revision_origin': "kernelci",
                'revision_origin_id': revision_id,

                'valid': build_kci['status'] == "PASS",
                'architecture': build_kci['arch'],
                'log_url': build_kci['build_log'],
                'start_time': created_on.isoformat(),
                'duration': build_kci['build_time'],
                'misc': {
                    key:build_kci[key] for key in [
                        'compiler',
                        'compiler_version',
                        'cross_compile',
                        'defconfig_full',
                        'kernel_version',
                        'kernel_config',
                        'kconfig_fragments',
                        'kernel_image',
                        'kernel_image_size',
                        'vmlinux_bss_size',
                        'vmlinux_data_size',
                        'vmlinux_file_size',
                        'vmlinux_text_size',
                        'modules_size',
                        'errors',
                        'warnings',
                    ]
                },
            }
            builds[build_id] = build

        env_desc = "/".join([tg['lab_name'], tg['board']])
        if tg['board_instance']:
            env_desc += "/" + tg['board_instance']
        if not env_desc in environments:
            env = {
                'origin': "kernelci",
                'origin_id': env_desc,
                'description': env_desc,
                'misc': {
                    key:tg[key] for key in ['arch', 'mach', 'device_type', 'board_instance', 'dtb', 'load_addr', 'initrd_addr', 'dtb_addr']
                }
            }
            # FIXME
            if env['misc']['dtb'] == "None":
                env['misc']['dtb'] = None
            environments[env_desc] = env
        handle_test_group(tg, build, env, "")

        # For now just send a few results
        tg_count += 1
        #if tg_count >= 100: 
        if len(tests) >= 10000: 
            break

    print("INFO: Stopping after %s test groups, %s test cases" % (tg_count, len(tests)))
    kcidb_export["revisions"] = list(revisions.values())
    kcidb_export["builds"] = list(builds.values())
    kcidb_export["environments"] = list(environments.values())
    kcidb_export["tests"] = list(tests.values())
    
    fp = open("kernelci.json", "w")
    json.dump(kcidb_export, fp, indent=4)
    fp.close()
    
if __name__ == "__main__":
    main()
