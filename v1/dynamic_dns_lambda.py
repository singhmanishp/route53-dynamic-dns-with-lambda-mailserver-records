# Diversified implementation to support mail server setup under ddns environment

# Script variables use lower_case_

from __future__ import print_function

import json
import boto3

# Tell the script where to find the configuration file.
config_s3_region = 'eu-west-1'
config_s3_bucket = <put your buckt here>
config_s3_key = 'DynDNSConf.txt'
client = boto3.client('route53')


''' This function pulls the json config file from S3 and
    returns a python dictionary.
    It is called by the run_set_mode function.'''


def read_s3_config():
    # Define the S3 client.
    s3_client = boto3.client(
        's3',
        config_s3_region,
    )

    # Download the config to /tmp
    s3_client.download_file(
        config_s3_bucket,
        config_s3_key,
        '/tmp/%s' % config_s3_key
    )
    # Open the config and return the json as a dictionary.
    full_config = (open('/tmp/%s' % config_s3_key).read())
    return json.loads(full_config)

''' This function calls client to get the current values for 
    the record types mentioned in the configuration.
    '''


def run_get_mode(key, route_53_record_name):
    # Try to read the config, and error if you can't.
    try:
        full_config = read_s3_config()
    except:
        return_status = 'fail'
        return_message = 'There was an issue finding ' \
                         'or reading the S3 config file.'
        return {'return_status': return_status,
                'return_message': return_message}

    record_config_set = full_config[route_53_record_name]
    # the Route 53 Zone you created for the script
    route_53_zone_id = record_config_set['route_53_zone_id']
    shared_secret = record_config_set['shared_secret']

    if key != shared_secret:
        return_status = 'fail'
        return_message = 'Invalid key.'
        return_dict = {'return_status': return_status,
                       'return_message': return_message}

    # Query Route 53 for the current DNS records. Including email server related records
    hosted_zone_data = client.list_resource_record_sets(
        HostedZoneId=route_53_zone_id,
        StartRecordName=route_53_record_name)
    hosted_zone_data['HostedZoneId'] = route_53_zone_id

    return  hosted_zone_data


''' This function calls client to see if the current Route 53 
    DNS record matches the client's current IP.
    If not it calls client to set the DNS record to the current IP.
    It is called by the main lambda_handler function.
    '''


def run_set_mode(key, route_53_record_name, public_ip):
    # get the existing data first and then modify
    route53_get_response = run_get_mode(key, route_53_record_name)
    # If no records were found, client returns null.
    # Set route53_ip and stop evaluating the null response.
    if not route53_get_response:
        route53_ip = '0'
    # Pass the fail message up to the main function.

    # GOAL=> replace the IP address of the A record, and replace the ip or reverse of the IP, where ever it is found

    # First grab the current IP address from 'A' record type
    for eachRecord in route53_get_response['ResourceRecordSets']:

        if eachRecord['Name'] == route_53_record_name and eachRecord['Type'] == 'A' :
            # If there's a single record, pass it along.
            if len(eachRecord['ResourceRecords']) == 1:
                for eachSubRecord in eachRecord['ResourceRecords']:
                    currentroute53_ip = eachSubRecord['Value']
            # Error out if there is more than one value for the record set.
            elif len(eachRecord['ResourceRecords']) > 1:
                return_status = 'fail'
                return_message = 'You should only have a single value for' \
                                 ' your dynamic record.  You currently have more than one.'
                return {'return_status': return_status,
                        'return_message': return_message}
        # remove reverse lookup entries as they are going to be new one
        if eachRecord['Type'] == 'PTR':
            client.change_resource_record_sets(
                HostedZoneId=route53_get_response['HostedZoneId'],
                ChangeBatch={
                    'Changes': [
                        {
                            'Action': 'DELETE',
                            'ResourceRecordSet': eachRecord
                        }
                    ]
                }
            )

    # Set the DNS records to the current IP.

    # replace currentroute53_ip with the public_ip
    current_route53_record_set_string = json.dumps(route53_get_response)
    current_route53_record_set_string = current_route53_record_set_string.replace(currentroute53_ip, public_ip)

    current_route53_record_set_string = current_route53_record_set_string.replace(
        '.'.join(reversed(currentroute53_ip.split('.'))),
        '.'.join(reversed(public_ip.split('.'))))


    new_route53_record_set = json.loads(current_route53_record_set_string)

    for eachRecordSet in new_route53_record_set['ResourceRecordSets']:
        if(eachRecordSet['Type'] == 'NS' or eachRecordSet['Type'] == 'SOA' ):
            continue

        # print(json.dumps(eachRecordSet))
        client.change_resource_record_sets(
            HostedZoneId=route53_get_response['HostedZoneId'],
            ChangeBatch={
                'Changes': [
                    {
                        'Action': 'UPSERT',
                        'ResourceRecordSet': eachRecordSet
                    }
                ]
            }
        )
    return {'return_status': 'success',
            'return_message': 'set new ip: ' + public_ip}


''' The function that Lambda executes.
    It contains the main script logic, calls
    and returns the output back to API Gateway'''


def lambda_handler(event, context):
    # Set event data from the API Gateway to variables.
    execution_mode = event['execution_mode']
    source_ip = event['source_ip']
    route_53_record_name = event['set_hostname']
    key = event['key']

    # For get mode, reflect the client's public IP address and exit.
    if execution_mode == 'get':
        return_dict = run_get_mode(key, route_53_record_name)
    # Proceed with set mode to create or update the DNS record.
    elif execution_mode == 'set':
        return_dict = run_set_mode(key, route_53_record_name, source_ip)
    else:
        return_status = 'fail'
        return_message = 'You must pass mode=get or mode=set arguments.'
        return_dict = {'return_status': return_status,
                       'return_message': return_message}
    # This Lambda function always exits as a success
    # and passes success or failure information in the json message.
    return return_dict
