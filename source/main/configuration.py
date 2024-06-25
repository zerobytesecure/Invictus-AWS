"""File used for the configuration collection."""

from source.utils.utils import create_s3_if_not_exists, PREPARATION_BUCKET, ROOT_FOLDER, create_command, create_folder, write_file, write_s3, set_clients
import source.utils.utils
from source.utils.enum import *
import json, boto3
from time import sleep


class Configuration:

    results = {}
    bucket = ""
    region = None
    services = {}
    dl = None

    def __init__(self, region, dl):
        """Handle the constructor of the Configuration class.
        
        Parameters
        ----------
        region : str
            Region in which to tool is executed
        dl : bool
            True if the user wants to download the results, False if he wants the results to be written in a s3 bucket
        """
        self.region = region
        self.dl = dl
        if not self.dl:
            self.bucket = create_s3_if_not_exists(self.region, PREPARATION_BUCKET)

    def self_test(self):
        """Test function."""
        print("[+] Configuration test passed")

    def execute(self, services, regionless):
        """Handle the main function of the class. Run every configuration function and then write the results where asked.
        
        Parameters
        ---------
        services : list
            Array used to write the results of the different configuration functions
        regionless : str
            "not-all" if the tool is used on only one region. First region to run the tool on otherwise
        """
        print(f"[+] Beginning Configuration Extraction")

        set_clients(self.region)

        self.services = services

        if (regionless != "" and regionless == self.region) or regionless == "not-all":
            self.get_configuration_s3()
            self.get_configuration_iam()
            self.get_configuration_cloudtrail()
            self.get_configuration_route53()
        
        self.get_configuration_wafv2()
        self.get_configuration_lambda()
        self.get_configuration_vpc()
        self.get_configuration_elasticbeanstalk()

        self.get_configuration_ec2()
        self.get_configuration_dynamodb()
        self.get_configuration_rds()

        self.get_configuration_cloudwatch()
        self.get_configuration_guardduty()
        self.get_configuration_detective()
        self.get_configuration_inspector2()
        self.get_configuration_maciev2()

        if self.dl:
            confs = ROOT_FOLDER + self.region + "/configurations/"
            create_folder(confs)
            with tqdm(desc="[+] Writing results", leave=False, total = len(self.results)) as pbar:
                for el in self.results:
                    write_file(
                        confs + f"{el}.json",
                        "w",
                        json.dumps(self.results[el], indent=4, default=str),
                    )
                    pbar.update() 
                    sleep(0.1)
            print(f"[+] Configuration results stored in the folder {confs}")
        else:
            with tqdm(desc="[+] Writing results", leave=False, total = len(self.results)) as pbar:
                for el in self.results:
                    write_s3(
                        self.bucket,
                        f"{self.region}/configuration/{el}.json",
                        json.dumps(self.results, indent=4, default=str),
                    )
                    pbar.update() 
                    sleep(0.1)
            print(f"[+] Configurations results stored in the bucket {self.bucket}")

    def get_configuration_s3(self):
        """Retrieve multiple elements of the configuration of the existing s3 buckets.""" 
        s3_list = self.services["s3"]

        '''
        In the first part, we verify that the enumeration of the service is already done. 
        If it doesn't, we redo it.
        If it is, we verify if the service is available or not.
        '''

        if s3_list["count"] == -1:
            elements = s3_lookup()
            
            if len(elements) == 0:
                self.display_progress(0, "s3")
                return

        elif s3_list["count"] == 0:
            self.display_progress(0, "s3")
            return
        else:
            elements = s3_list["elements"]

        '''
        In this part, we get some parts of the configuration of each element of the service (s3 in this case)
        Then all the results are added to a same json file.
        This way of working is used in every function of this class.
        '''

        objects = {}
        buckets_logging = {}
        buckets_policy = {}
        buckets_acl = {}
        buckets_location = {}

        with tqdm(desc="[+] Getting S3 Configuration", leave=False, total = len(elements)) as pbar:
            for bucket in elements:
                bucket_name = bucket["Name"]
                objects[bucket_name] = []

                # list_objects_v2

                objects[bucket_name] = simple_paginate(S3_CLIENT, "list_objects_v2", Bucket=bucket_name)

                # get_bucket_logging

                response = try_except(S3_CLIENT.get_bucket_logging, Bucket=bucket_name)
                if "LoggingEnabled" in response:
                    buckets_logging[bucket_name] = response
                else:
                    buckets_logging[bucket_name] = {"LoggingEnabled": False}

                # get_bucket_policy

                response = try_except(S3_CLIENT.get_bucket_policy, Bucket=bucket_name)
                buckets_policy[bucket_name] = json.loads(response.get("Policy", "{}"))

                # get_bucket_acl

                response = try_except(S3_CLIENT.get_bucket_acl, Bucket=bucket_name)
                response.pop("ResponseMetadata", None)
                response = fix_json(response)
                buckets_acl[bucket_name] = response

                # get_bucket_location

                response = try_except(S3_CLIENT.get_bucket_location, Bucket=bucket_name)
                response.pop("ResponseMetadata", None)
                response = fix_json(response)
                buckets_location[bucket_name] = response
                pbar.update()
          
        # Presenting the results properly
        results = []
        results.append(
            create_command("aws s3api list-objects-v2 --bucket <name>", objects)
        )
        results.append(
            create_command(
                "aws s3api get-bucket-logging --bucket <name>", buckets_logging
            )
        )
        results.append(
            create_command(
                "aws s3api get-bucket-policy --bucket <name>", buckets_policy
            )
        )
        results.append(
            create_command("aws s3api get-bucket-acl --bucket <name>", buckets_acl)
        )
        results.append(
            create_command(
                "aws s3api get-bucket-location --bucket <name>", buckets_location
            )
        )
        self.results["s3"] = results
        self.display_progress(len(results), "s3")

    def get_configuration_wafv2(self):
        """Retrieve multiple elements of the configuration of the existing web acls.""" 
        waf_list = self.services["wafv2"]

        if waf_list["count"] == -1:
            wafs = misc_lookup("WAF", source.utils.utils.WAF_CLIENT.list_web_acls, "NextMarker", "WebACLs", Scope="REGIONAL", Limit=100)
        
            identifiers = []
            for el in wafs:
                identifiers.append(el["ARN"])

            if len(identifiers) == 0:
                self.display_progress(0, "wafv2")
                return

        elif waf_list["count"] == 0:
            self.display_progress(0, "wafv2")
            return
        else:
            identifiers = waf_list["ids"]

        logging_config = {}
        rule_groups = {}
        managed_rule_sets = {}
        ip_sets = {}
        resources = {}

        with tqdm(desc="[+] Getting WAF configuration", leave=False, total = len(identifiers)) as pbar:
            for arn in identifiers:

                # get_logging_configuration

                response = try_except(source.utils.utils.WAF_CLIENT.get_logging_configuration, ResourceArn=arn)
                response.pop("ResponseMetadata", None)
                response = fix_json(response)
                if "WAFNonexistentItemException" in response["error"]:
                    response["error"] = "[!] Error: The Logging feature is not enabled for the selected Amazon WAF Web Access Control List (Web ACL)."
                logging_config[arn] = response

                # list_rules_groups
                # Use of misc_lookup as not every results are listed at the first call if there are a lot

                rule_groups[arn] = simple_misc_lookup("WAF", source.utils.utils.WAF_CLIENT.list_rule_groups, "NextMarker", Scope="REGIONAL", Limit=100)


                # list_managed_rule_sets

                managed_rule_sets[arn] = simple_misc_lookup("WAF", source.utils.utils.WAF_CLIENT.list_managed_rule_sets, "NextMarker", Scope="REGIONAL", Limit=100)

                # list_ip_sets

                ip_sets[arn] = simple_misc_lookup("WAF", source.utils.utils.WAF_CLIENT.list_ip_sets, "NextMarker", Scope="REGIONAL", Limit=100)

                #list_resources_for_web_acl

                response = try_except("WAF", source.utils.utils.WAF_CLIENT.list_resources_for_web_acl, WebACLArn=arn)
                response.pop("ResponseMetadata", None)
                response = fix_json(response)
                resources[arn] = response
                pbar.update()

        results = []
        results.append(
            create_command(
                "aws wafv2 get-logging-configuration --resource-arn <arn>",
                logging_config,
            )
        )
        results.append(
            create_command("aws wafv2 list-rule-groups --scope REGIONAL", rule_groups)
        )
        results.append(
            create_command(
                "aws wafv2 list-managed-rule-sets --scope REGIONAL", managed_rule_sets
            )
        )
        results.append(
            create_command("aws wafv2 list-ip-sets --scope REGIONAL", ip_sets)
        )
        results.append(
            create_command(
                "aws wafv2 list-resources-for-web-acl --resource-arn <arn>", resources
            )
        )

        self.results["wafv2"] = results
        self.display_progress(len(results), "wafv2")

    def get_configuration_lambda(self):
        """Retrieve multiple elements of the configuration of the existing lambdas.""" 
        lambda_list = self.services["lambda"]

        if lambda_list["count"] == -1:
            functions = paginate(source.utils.utils.LAMBDA_CLIENT, "list_functions", "Functions")

            if len(functions) == 0:
                self.display_progress(0, "lambda")
                return
            
            identifiers = []
            for function in functions:
                identifiers.append(function["FunctionName"])

        elif lambda_list["count"] == 0:
            self.display_progress(0, "lambda")
            return
        else:
            identifiers = lambda_list["ids"]

        function_config = {}

        with tqdm(desc="[+] Getting LAMBDA configuration", leave=False, total = len(identifiers)) as pbar:
            for name in identifiers:
                if name == "":
                    continue

                # get_function_configuration

                response = try_except(
                    source.utils.utils.LAMBDA_CLIENT.get_function_configuration, FunctionName=name
                )
                response.pop("ResponseMetadata", None)
                response = fix_json(response)
                function_config[name] = response
                pbar.update()

        # get_account_settings

        response = try_except(source.utils.utils.LAMBDA_CLIENT.get_account_settings)
        response.pop("ResponseMetadata", None)
        response = fix_json(response)
        account_settings = response

        # list_event_source_mappings

        event_source_mappings = simple_paginate(source.utils.utils.LAMBDA_CLIENT, "list_event_source_mappings")

        results = []
        results.append(
            create_command(
                "aws lambda get-function-configuration --function-name <name>",
                function_config,
            )
        )
        results.append(
            create_command("aws lambda get-account-settings", account_settings)
        )
        results.append(
            create_command(
                "aws lambda list-event-source-mappings", event_source_mappings
            )
        )

        self.results["lambda"] = results
        self.display_progress(len(results), "lambda")
   
    def get_configuration_vpc(self):
        """Retrieve multiple elements of the configuration of the existing vpcs.""" 
        vpc_list = self.services["vpc"]

        if vpc_list["count"] == -1:

            vpcs = paginate(source.utils.utils.EC2_CLIENT, "describe_vpcs", "Vpcs")

            if len(vpcs) == 0:
                self.display_progress(0, "vpc")
                return
            
            identifiers = []
            for vpc in vpcs:
                identifiers.append(vpc["VpcId"])

        elif vpc_list["count"] == 0:
            self.display_progress(0, "vpc")
            return
        else:
            identifiers = vpc_list["ids"]

        dns_support = {}
        dns_hostnames = {}

        with tqdm(desc="[+] Getting VPC configuration", leave=False, total = len(identifiers)) as pbar:
            for id in identifiers:
                if id == "":
                    continue

                # describe_vpc_attribute

                response = try_except(
                    source.utils.utils.EC2_CLIENT.describe_vpc_attribute,
                    VpcId=id,
                    Attribute="enableDnsSupport",
                )
                response.pop("ResponseMetadata", None)
                response = fix_json(response)
                dns_support[id] = response

                # describe_vpc_attribute

                response = try_except(
                    source.utils.utils.EC2_CLIENT.describe_vpc_attribute,
                    VpcId=id,
                    Attribute="enableDnsHostnames",
                )
                response.pop("ResponseMetadata", None)
                response = fix_json(response)
                dns_hostnames[id] = response
                pbar.update()

        # describe_flow_logs

        flow_logs = simple_paginate(source.utils.utils.EC2_CLIENT, "describe_flow_logs")

        # describe_vpc_peering_connections

        peering_connections = simple_paginate(source.utils.utils.EC2_CLIENT, "describe_vpc_peering_connections")

        # describe_vpc_endpoint_connections

        endpoint_connections = simple_paginate(source.utils.utils.EC2_CLIENT, "describe_vpc_endpoint_connections")

        # describe_vpc_endpoint_service_configurations

        endpoint_service_config = simple_paginate(source.utils.utils.EC2_CLIENT, "describe_vpc_endpoint_service_configurations")

        # describe_vpc_classic_link

        response = try_except(source.utils.utils.EC2_CLIENT.describe_vpc_classic_link)
        response.pop("ResponseMetadata", None)
        response = fix_json(response)
        classic_links = response

        # describe_vpc_endpoints

        endpoints = simple_paginate(source.utils.utils.EC2_CLIENT, "describe_vpc_endpoints")

        # describe_local_gateway_route_table_vpc_associations

        response = simple_paginate(source.utils.utils.EC2_CLIENT, "describe_local_gateway_route_table_vpc_associations")
        local_gateway_route_table = response

        results = []
        results.append(
            create_command(
                "aws ec2 describe-vpc-attribute --vpc-id <id> --attribute enableDnsSupport",
                dns_support,
            )
        )
        results.append(
            create_command(
                "aws ec2 describe-vpc-attribute --vpc-id <id> --attribute enableDnsHostnames",
                dns_hostnames,
            )
        )
        results.append(create_command("aws ec2 describe-flow-logs", flow_logs))
        results.append(
            create_command(
                "aws ec2 describe-vpc-peering-connections", peering_connections
            )
        )
        results.append(
            create_command(
                "aws ec2 describe-vpc-endpoint-connections", endpoint_connections
            )
        )
        results.append(
            create_command(
                "aws ec2 describe-vpc-endpoint-service-configurations",
                endpoint_service_config,
            )
        )
        results.append(
            create_command("aws ec2 describe-vpc-classic-link", classic_links)
        )
        results.append(create_command("aws ec2 describe-vpc-endpoints", endpoints))
        results.append(
            create_command(
                "aws ec2 describe-local-gateway-route-table-vpc-associations",
                local_gateway_route_table,
            )
        )

        self.results["vpc"] = results
        self.display_progress(len(results), "vpc")
    
    def get_configuration_elasticbeanstalk(self):
        """Retrieve multiple elements of the configuration of the existing elasticbeanstalk environments."""
        eb_list = self.services["elasticbeanstalk"]

        if eb_list["count"] == -1:
            environments = paginate(source.utils.utils.EB_CLIENT, "describe_environments", "Environments")

            if len(environments) == 0:
                self.display_progress(0, "elasticbeanstalk")
                return
            
            identifiers = []
            for env in environments:
                identifiers.append(env["EnvironmentId"])

        elif eb_list["count"] == 0:
            self.display_progress(0, "elasticbeanstalk")
            return
        else:
            identifiers = []
            environments = eb_list["elements"]
            for el in environments:
                identifiers.append(el["EnvironmentId"])

        resources = {}
        managed_actions = {}
        managed_action_history = {}
        instances_health = {}

        with tqdm(desc="[+] Getting ELASTICBEANSTALK configuration", leave=False, total = len(identifiers)) as pbar:
            for id in identifiers:
                if id == "":
                    continue
                resources[id] = []

                # describe_environment_resources

                response = try_except(
                    source.utils.utils.EB_CLIENT.describe_environment_resources, EnvironmentId=id
                )
                response.pop("ResponseMetadata", None)
                response = fix_json(response)
                resources[id] = response

               #  describe_environment_managed_actions

                managed_actions[id] = []
                response = try_except(
                    source.utils.utils.EB_CLIENT.describe_environment_managed_actions, EnvironmentId=id
                )
                response.pop("ResponseMetadata", None)
                response = fix_json(response)
                managed_actions[id] = response

                # describe_environment_managed_action_history

                managed_action_history[id] = []
                managed_action_history[id] = simple_paginate(source.utils.utils.EB_CLIENT, "describe_environment_managed_action_history", EnvironmentId=id)

                # describe_instances_health

                instances_health[id] = []
                instances_health[id] = simple_misc_lookup("ELASTICBEANSTALK", source.utils.utils.EB_CLIENT.describe_instances_health, "NextToken", EnvironmentId=id)
                pbar.update()

        # describe_applications

        response = try_except(source.utils.utils.EB_CLIENT.describe_applications)
        response.pop("ResponseMetadata", None)
        data = fix_json(response)
        applications = data

        # describe_account_attributes

        response = try_except(source.utils.utils.EB_CLIENT.describe_account_attributes)
        response.pop("ResponseMetadata", None)
        data = response
        account_attributes = data

        results = []
        results.append(
            create_command(
                "aws elasticbeanstalk describe-environment-resources --environment-id <id>",
                resources,
            )
        )
        results.append(
            create_command(
                "aws elasticbeanstalk describe-environment-managed-actions --environment-id <id>",
                managed_actions,
            )
        )
        results.append(
            create_command(
                "aws elasticbeanstalk describe-environment-managed-action-history --environment-id <id>",
                managed_action_history,
            )
        )
        results.append(
            create_command(
                "aws elasticbeanstalk describe-instances-health --environment-id <id>",
                instances_health,
            )
        )
        results.append(
            create_command("aws elasticbeanstalk describe-environments", environments)
        )
        results.append(
            create_command("aws elasticbeanstalk describe-applications", applications)
        )
        results.append(
            create_command(
                "aws elasticbeanstalk describe-account-attributes", account_attributes
            )
        )

        self.results["eb"] = results
        self.display_progress(len(results), "elasticbeanstalk")
    
    def get_configuration_route53(self):
        """Retrieve multiple elements of the configuration of the existing routes53 hosted zones.""" 
        route53_list = self.services["route53"]

        if route53_list["count"] == -1:
            hosted_zones = paginate(source.utils.utils.ROUTE53_CLIENT, "list_hosted_zones", "HostedZones")

            if len(hosted_zones) == 0:
                self.display_progress(0, "route53")
                return
            
            identifiers = []
            for zone in hosted_zones:
                identifiers.append(zone["Id"])

        elif route53_list["count"] == 0:
            self.display_progress(0, "route53")
            return
        else:
            identifiers = route53_list["ids"]

        # list_traffic_policies

        get_traffic_policies = list_traffic_policies_lookup(source.utils.utils.ROUTE53_CLIENT.list_traffic_policies)

        # list_resolver_configs

        resolver_configs = simple_paginate(source.utils.utils.ROUTE53_RESOLVER_CLIENT, "list_resolver_configs")

        # list_firewall_configs

        resolver_firewall_config = simple_paginate(source.utils.utils.ROUTE53_RESOLVER_CLIENT, "list_firewall_configs")

        # list_resolver_query_log_configs

        resolver_log_configs = simple_paginate(source.utils.utils.ROUTE53_RESOLVER_CLIENT, "list_resolver_query_log_configs")

        get_zones = []
        results = []

        # get_hosted_zone

        with tqdm(desc="[+] Getting ROUTE53 configuration", leave=False, total = len(identifiers)) as pbar:
            for id in identifiers:
                response = try_except(source.utils.utils.ROUTE53_CLIENT.get_hosted_zone, Id=id)
                response.pop("ResponseMetadata", None)
                response = fix_json(response)
                get_zones.append(response)
                pbar.update()

        results.append(
            create_command("aws route53 list-traffic-policies", get_traffic_policies)
        )
        results.append(
            create_command("aws route53 get-hosted-zone --id <string>", get_zones)
        )
        results.append(
            create_command(
                "aws route53resolver list-resolver-configs", resolver_configs
            )
        )
        results.append(
            create_command(
                "aws route53resolver list-resolver-query-log-configs",
                resolver_log_configs,
            )
        )
        results.append(
            create_command(
                "aws route53resolver list-firewall-configs ", resolver_firewall_config
            )
        )

        self.results["route53"] = results
        self.display_progress(len(results), "route53")
        return
    
    def get_configuration_ec2(self):
        """Retrieve multiple elements of the configuration of the existing ec2 instances.""" 
        ec2_list = self.services["ec2"]

        if ec2_list["count"] == -1:
            elements = ec2_lookup()

            if len(elements) == 0:
                self.display_progress(0, "ec2")
                return

            else:
                self.display_progress(0, "ec2")
                return

        elif ec2_list["count"] == 0:
            self.display_progress(0, "ec2")
            return

        # describe_export_tasks

        response = try_except(source.utils.utils.EC2_CLIENT.describe_export_tasks)
        response.pop("ResponseMetadata", None)
        export = fix_json(response)

        # describe_fleets

        fleets = simple_paginate(source.utils.utils.EC2_CLIENT, "describe_fleets")

        # describe_hosts

        hosts = simple_paginate(source.utils.utils.EC2_CLIENT, "describe_hosts")

        # describe_key_pairs

        response = try_except(source.utils.utils.EC2_CLIENT.describe_key_pairs)
        response.pop("ResponseMetadata", None)
        key_pairs = fix_json(response)

        # describe_volumes

        volumes = simple_paginate(source.utils.utils.EC2_CLIENT, "describe_volumes")

        # describe_subnets

        subnets = simple_paginate(source.utils.utils.EC2_CLIENT, "describe_subnets")

        # describe_security_groups

        sec_groups = simple_paginate(source.utils.utils.EC2_CLIENT, "describe_security_groups")

        # describe_route_tables

        route_tables = simple_paginate(source.utils.utils.EC2_CLIENT, "describe_route_tables")

        # describe_snapshots

        snapshots = simple_paginate(source.utils.utils.EC2_CLIENT, "describe_snapshots")

        results = []
        results.append(create_command("aws ec2 describe-export-tasks", export))
        results.append(create_command("aws ec2 describe-fleets", fleets))
        results.append(create_command("aws ec2 describe-hosts", hosts))
        results.append(create_command("aws ec2 describe-key-pairs", key_pairs))
        results.append(create_command("aws ec2 describe-volumes", volumes))
        results.append(create_command("aws ec2 describe-subnets", subnets))
        results.append(create_command("aws ec2 describe-security-groups", sec_groups))
        results.append(create_command("aws ec2 describe-route-tables", route_tables))
        results.append(create_command("aws ec2 describe-snapshots", snapshots))

        self.results["ec2"] = results
        self.display_progress(len(results), "ec2")
   
    def get_configuration_iam(self):
        """Retrieve multiple elements of the configuration of the existing iam users.""" 
        iam_list = self.services["iam"]

        if iam_list["count"] == -1:
            elements = paginate(source.utils.utils.IAM_CLIENT, "list_users", "Users")

            if len(elements) == 0:
                self.display_progress(0, "ec2")
                return

        elif iam_list["count"] == 0:
            self.display_progress(0, "iam")
            return
        
        # get_account_summary

        response = try_except(source.utils.utils.IAM_CLIENT.get_account_summary)
        response.pop("ResponseMetadata", None)
        get_summary = fix_json(response)

        # get_account_authorization_details

        get_auth_details = simple_paginate(source.utils.utils.IAM_CLIENT, "get_account_authorization_details")

        # list_ssh_public_keys

        list_ssh_pub_keys = simple_paginate(source.utils.utils.IAM_CLIENT, "list_ssh_public_keys")

        # list_mfa_devices

        list_mfa_devices = simple_paginate(source.utils.utils.IAM_CLIENT, "list_mfa_devices")

        results = []
        results.append(create_command("aws iam get-account-summary", get_summary))
        results.append(
            create_command(
                "aws iam get-account-authorization-details", get_auth_details
            )
        )
        results.append(
            create_command("aws iam list-ssh-public-keys  ", list_ssh_pub_keys)
        )
        results.append(create_command("aws iam list-mfa-devices ", list_mfa_devices))

        self.results["iam"] = results
        self.display_progress(len(results), "iam")
        return
    
    def get_configuration_dynamodb(self):
        """Retrieve multiple elements of the configuration of the existing dynamodb tables.""" 
        dynamodb_list = self.services["s3"]

        if dynamodb_list["count"] == -1:
            tables = paginate(source.utils.utils.DYNAMODB_CLIENT, "list_tables", "TableNames")

            if len(tables) == 0:
                self.display_progress(0, "dynamodb")
                return

        elif dynamodb_list["count"] == 0:
            self.display_progress(0, "dynamodb")
            return
        else:
            tables = dynamodb_list["elements"]

        tables_info = []
        export_info = []

        # list_backups

        backups = simple_paginate(source.utils.utils.DYNAMODB_CLIENT, "list_backups")

        # list_exports

        list_exports = misc_lookup("DYNAMOBDB", source.utils.utils.DYNAMODB_CLIENT.list_exports, "NextToken", "ExportSummaries", MaxResults=100)

        # describe_table

        with tqdm(desc="[+] Getting DYNAMODB configuration", leave=False, total = len(tables)) as pbar:
            for table in tables:
                response = try_except(source.utils.utils.DYNAMODB_CLIENT.describe_table, TableName=table)
                response.pop("ResponseMetadata", None)
                get_table = fix_json(response)
                tables_info.append(get_table)
                pbar.update()

        # describe_export

        for export in list_exports:
            response = try_except(
                source.utils.utils.DYNAMODB_CLIENT.describe_export, ExportArn=export.get("ExportArn", "")
            )
            response.pop("ResponseMetadata", None)
            get_export = fix_json(response)
            export_info.append(get_export)

        results = []
        results.append(create_command("aws dynamodb list-backups", backups))
        results.append(
            create_command(
                "aws dynamodb describe-table --table-name <name>", tables_info
            )
        )
        results.append(create_command("aws dynamodb list-exports", list_exports))
        results.append(
            create_command(
                "aws dynamodb describe-export --export-arn <arn>", export_info
            )
        )

        self.results["dynamodb"] = results
        self.display_progress(len(results), "dynamodb")
        return
    
    def get_configuration_rds(self):
        """Retrieve multiple elements of the configuration of the existing rds instances.""" 
        rds_list = self.services["rds"]

        if rds_list["count"] == -1:
            elements = paginate(source.utils.utils.RDS_CLIENT, "describe_db_instances", "DBInstances")

            if len(elements) == 0:
                self.display_progress(0, "rds")
                return

        elif rds_list["count"] == 0:
            self.display_progress(0, "rds")
            return

        # describe_db_clusters

        clusters = simple_paginate(source.utils.utils.RDS_CLIENT, "describe_db_clusters")

        # describe_db_snapshots

        snapshots = simple_paginate(source.utils.utils.RDS_CLIENT, "describe_db_snapshots")

        # describe_db_proxies

        proxies = simple_paginate(source.utils.utils.RDS_CLIENT, "describe_db_proxies")

        results = []
        results.append(create_command("aws rds describe-db-clusters", clusters))
        results.append(create_command("aws rds describe-db-snapshots", snapshots))
        results.append(create_command("aws rds describe-db-proxies ", proxies))

        self.results["rds"] = results
        self.display_progress(len(results), "rds")
        return
    
    def get_configuration_guardduty(self):
        """Retrieve multiple elements of the configuration of the existing guardduty detectors.""" 
        guardduty_list = self.services["guardduty"]

        if guardduty_list["count"] == -1:
            detectors = paginate(source.utils.utils.GUARDDUTY_CLIENT, "list_detectors", "DetectorIds")

            if len(detectors) == 0:
                self.display_progress(0, "guardduty")
                return

        elif guardduty_list["count"] == 0:
            self.display_progress(0, "guardduty")
            return
        else:
            detectors = guardduty_list["ids"]

        detectors = {}
        filters = {}
        filter_data = {}
        publishing_destinations = {}
        threat_intel = {}
        ip_sets = {}

        with tqdm(desc="[+] Getting GUARDDUTY configuration", leave=False, total = len(detectors)) as pbar:
            for detector in detectors:

                # get_detector

                response = try_except(source.utils.utils.GUARDDUTY_CLIENT.get_detector, DetectorId=detector)
                response.pop("ResponseMetadata", None)
                detectors[detector] = response

                # list_filters

                filters[detector] = simple_paginate(source.utils.utils.GUARDDUTY_CLIENT, "list_filters", DetectorId=detector)

                filter_names = []
                for el in filters[detector]:
                    filter_names.extend(el["FilterNames"])

                # get_filter

                for filter_name in filter_names:
                    filter_data[detector] = []
                    response = try_except(
                        source.utils.utils.GUARDDUTY_CLIENT.get_filter,
                        DetectorId=detector,
                        FilterName=filter_name,
                    )
                    response.pop("ResponseMetadata", None)
                    filter_data[detector].extend(response)

                # list_publishing_destinations

                publishing_destinations[detector] = simple_misc_lookup(
                    "GUARDDUTY",
                    source.utils.utils.GUARDDUTY_CLIENT.list_publishing_destinations, 
                    "NextToken", 
                    DetectorId=detector, 
                    MaxResults=100
                )

                # list_threat_intel_sets

                threat_intel[detector] = simple_paginate(source.utils.utils.GUARDDUTY_CLIENT, "list_threat_intel_sets", DetectorId=detector)

                # list_ip_sets

                ip_sets[detector] = simple_paginate(source.utils.utils.GUARDDUTY_CLIENT, "list_ip_sets", DetectorId=detector)

                pbar.update()
           

        results = []
        results.append(
            create_command("guardduty get-detector --detector-id <id>", detectors)
        )
        results.append(
            create_command("guardduty list-filters --detector-id <id>", filters)
        )
        results.append(
            create_command(
                "guardduty get-filter --detector-id <id> --filter-name <filter>",
                filter_data,
            )
        )
        results.append(
            create_command(
                "guardduty list-publishing-destinations --detector-id <id>",
                publishing_destinations,
            )
        )
        results.append(
            create_command(
                "guardduty list-threat-intel-sets --detector-id <id>", threat_intel
            )
        )
        results.append(
            create_command("guardduty list-ip-sets --detector-id <id>", ip_sets)
        )

        self.results["guardduty"] = results
        self.display_progress(len(results), "guardduty")
        return
    
    def get_configuration_cloudwatch(self):
        """Retrieve multiple elements of the configuration of the existing cloudwatch dashboards.""" 
        cloudwatch_list = self.services["cloudwatch"]

        if cloudwatch_list["count"] == -1:
            dashboards = paginate(source.utils.utils.CLOUDWATCH_CLIENT, "list_dashboards", "DashboardEntries")

            if len(dashboards) == 0:
                self.display_progress(0, "cloudwatch")
                return

        elif cloudwatch_list["count"] == 0:
            self.display_progress(0, "cloudwatch")
            return
        else:
            dashboards = cloudwatch_list["elements"]

        dashboards_data = {}
        with tqdm(desc="[+] Getting CLOUDWATCH configuration", leave=False, total = len(dashboards)) as pbar:
            for dashboard in dashboards:
                dashboard_name = dashboard["DashboardName"]
                if dashboard_name == "":
                    continue

                # get_dashboard

                response = try_except(
                    source.utils.utils.CLOUDWATCH_CLIENT.get_dashboard, DashboardName=dashboard_name
                )
                response.pop("ResponseMetadata", None)
                dashboards_data[dashboard_name] = fix_json(response)
                pbar.update()

        # list_metrics

        metrics = simple_paginate(source.utils.utils.CLOUDWATCH_CLIENT, "list_metrics")

        results = []
        results.append(
            create_command(
                "aws cloudwatch get-dashboard --name <name>", dashboards_data
            )
        )
        results.append(
            create_command("aws cloudwatch list-metrics --name <name>", metrics)
        )

        self.results["cloudwatch"] = results
        self.display_progress(len(results), "cloudwatch")
        return

    def get_configuration_maciev2(self):
        """Retrieve multiple elements of the configuration of the existing macie buckets.""" 
        macie_list = self.services["macie"]

        if macie_list["count"] == -1:
            elements = paginate(source.utils.utils.MACIE_CLIENT, "describe_buckets", "buckets")

            if len(elements) == 0:
                self.display_progress(0, "macie")
                return
        elif macie_list["count"] == 0:
            self.display_progress(0, "macie")
            return

        # get_finding_statistics

        response = try_except(source.utils.utils.MACIE_CLIENT.get_finding_statistics, groupBy="type")
        response.pop("ResponseMetadata", None)
        statistics_severity = fix_json(response)

        # get_finding_statistics

        response = try_except(
            source.utils.utils.MACIE_CLIENT.get_finding_statistics, groupBy="severity.description"
        )
        response.pop("ResponseMetadata", None)
        statistics_type = fix_json(response)

        results = []
        results.append(
            create_command(
                "aws macie2 get-finding-statistics --group-by severity.description",
                statistics_severity,
            )
        )
        results.append(
            create_command(
                "aws macie2 get-finding-statistics --group-by type", statistics_type
            )
        )

        self.results["macie"] = results
        self.display_progress(len(results), "macie")
        return
    
    def get_configuration_inspector2(self):
        """Retrieve multiple elements of the configuration of the existing inspector coverages.""" 
        inspector_list = self.services["inspector"]

        if inspector_list["count"] == 0:
            self.display_progress(0, "inspector")
            return
        
        coverage = paginate(source.utils.utils.INSPECTOR_CLIENT, "list_coverage", "coveredResources")

        if len(coverage) == 0:
            self.display_progress(0, "inspector")
            return

        # list_usage_totals

        usage = simple_paginate(source.utils.utils.INSPECTOR_CLIENT, "list_usage_totals")

        # list_account_permissions

        permission = simple_paginate(source.utils.utils.INSPECTOR_CLIENT, "list_account_permissions")

        results = []
        results.append(create_command("aws inspector2 list-coverage", coverage))
        results.append(create_command("aws inspector2 list-usage-totals", usage))
        results.append(
            create_command("aws inspector2 list-account-permissions", permission)
        )

        self.results["inspector"] = results
        self.display_progress(len(results), "inspector")
    
    def get_configuration_detective(self):
        """Retrieve multiple elements of the configuration of the existing detective graphs.""" 
        detective_list = self.services["detective"]

        if detective_list["count"] == -1:
            graphs = misc_lookup("DETECTIVE", source.utils.utils.DETECTIVE_CLIENT.list_graphs, "NextToken", "GraphList", MaxResults=100)

            if len(graphs) == 0:
                self.display_progress(0, "detective")
                return

        elif detective_list["count"] == 0:
            self.display_progress(0, "detective")
            return

        results = []
        results.append(create_command("aws detective list-graphs ", graphs))

        self.results["detective"] = results
        self.display_progress(len(results), "detective")
        print("finito detectivo")
    
    def get_configuration_cloudtrail(self):
        """Retrieve multiple elements of the configuration of the existing cloudtrail trails.""" 
        cloudtrail_list = self.services["cloudtrail"]

        if cloudtrail_list["count"] == -1:
            trails = paginate(source.utils.utils.CLOUDTRAIL_CLIENT, "list_trails", "Trails")

            if len(trails) == 0:
                self.display_progress(0, "cloudtrail")
                return

        elif cloudtrail_list["count"] == 0:
            self.display_progress(0, "cloudtrail")
            return
        else:
            trails = cloudtrail_list["elements"]

        trails_data = {}
        with tqdm(desc="[+] Getting CLOUDTRAIL configuration", leave=False, total = len(trails)) as pbar:
            for trail in trails:
                trail_name = trail.get("Name", "")
                if trail_name == "":
                    continue

                home_region = trail.get("HomeRegion")
                source.utils.utils.CLOUDTRAIL_CLIENT = boto3.client("cloudtrail", region_name=home_region)

                response = try_except(source.utils.utils.CLOUDTRAIL_CLIENT.get_trail, Name=trail_name)
                response.pop("ResponseMetadata", None)
                trails_data[trail_name] = fix_json(response)
                pbar.update()

        results = []
        results.append(create_command("aws cloudtrail list-trails", trails))
        results.append(
            create_command("aws cloudtrail get-trail --name <name>", trails_data)
        )

        self.results["cloudtrail"] = results
        self.display_progress(len(results), "cloudtrail")

    def display_progress(self, count, name):
        """Display if the configuration of the given service worked.

        Parameters
        ----------
        count : int
            != 0 a configuration file was created. 0 otherwise
        name : str
            Name of the service
        """
        if count != 0:
            print(
                "\t\u2705 "
                + name.upper()
                + "\033[1m"
                + " - JSON File Extracted "
                + "\033[0m"
            )
        else:
            print(
                " \t\u274c "
                + name.upper()
                + "\033[1m"
                + " - No Configuration"
                + "\033[0m"
            )
